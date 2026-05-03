"""Pure-Python rota validator — the back-half of the constraint engine.

The OR-Tools solver (`rota_solver.py`) builds rotas from scratch.  This
validator inspects an *already-assigned* rota and returns a list of
violations (matched against the rules from `rule_definitions.py`).  It is
used by:

    PATCH /api/rotas/{id}/cell      — re-validates after a manual edit
    POST  /api/rotas/{id}/validate  — full rota validation pass
    POST  /api/rotas/{id}/copy-from-previous  — surfaces clashes after copy

Violations are returned as:

    {
        "rule_id":        str,
        "rule_name":      str,
        "severity":       "hard" | "soft",
        "date":           str (YYYY-MM-DD) or None,
        "staff_initials": str or None,
        "message":        str,
        "affected_cells": [{"date": ..., "staff_initials": ...}, ...],
    }
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from solver.rule_definitions import RULES_BY_ID

WORKING_SHIFTS = {"D", "D*", "N", "*"}
DAY_COVER_SHIFTS = {"D", "D*"}
NIGHT_COVER_SHIFTS = {"N", "D*", "*"}
SHIFT_HOURS = {"D": 12, "D*": 14, "N": 12, "*": 0, "OFF": 0, "AL": 0, "TRN": 0, "": 0}
DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _dow_idx_for(date_str: str) -> int:
    """Monday=0 … Sunday=6 for an ISO date string."""
    from datetime import date as _date
    return _date.fromisoformat(date_str).weekday()


class _DowLookup:
    """Tiny dict-like lazy cache so `DOW_IDX.get(date_str)` works."""
    def get(self, d_str: str, default=None):
        try:
            return _dow_idx_for(d_str)
        except Exception:
            return default


DOW_IDX = _DowLookup()
DOW_FROM_STR = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _normalise_dow(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and 0 <= value <= 6:
        return value
    if isinstance(value, str):
        return DOW_FROM_STR.get(value.strip().lower()[:3])
    return None


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _date_range(start: date, weeks: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(weeks * 7)]


def _v(rule_id: str, severity: str, message: str,
       date_=None, staff_initials=None, affected_cells=None) -> dict:
    rule = RULES_BY_ID.get(rule_id, {})
    return {
        "rule_id": rule_id,
        "rule_name": rule.get("name", rule_id),
        "severity": severity,
        "date": date_,
        "staff_initials": staff_initials,
        "message": message,
        "affected_cells": affected_cells or
            ([{"date": date_, "staff_initials": staff_initials}]
             if date_ and staff_initials else []),
    }


def _mode_for(rules_config: dict | None, rule_id: str, default: str) -> str:
    if not rules_config:
        return default
    entry = rules_config.get(rule_id)
    if isinstance(entry, dict) and "mode" in entry:
        return entry["mode"]
    return default


# ---------------------------------------------------------------------------
def validate_rota(
    rota: dict[str, Any],
    staff: list[dict[str, Any]],
    rules_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate a fully-assigned rota.

    `rota` shape:
        {start_date, weeks, assignments: [{date, staff_initials, shift, locked}]}
    `staff` is a list of staff docs.
    `rules_config` is the per-rule mode/weight dict (from db.rules_config).
    """
    start = _parse_date(rota["start_date"])
    weeks = int(rota.get("weeks", 4))
    days = _date_range(start, weeks)
    day_strs = [d.isoformat() for d in days]
    day_str_set = set(day_strs)

    staff_by = {s["initials"]: s for s in staff}
    staff_inits = list(staff_by.keys())

    # Build a (date, init) -> {shift, locked} index, default blank
    cell: dict[tuple[str, str], dict] = {}
    for d_str in day_strs:
        for s in staff_inits:
            cell[(d_str, s)] = {"shift": "", "locked": False}
    for a in rota.get("assignments", []):
        if a["date"] in day_str_set and a["staff_initials"] in staff_by:
            cell[(a["date"], a["staff_initials"])] = {
                "shift": a.get("shift", ""),
                "locked": bool(a.get("locked", False)),
            }

    violations: list[dict] = []

    # --- day_cover (immovable) -------------------------------------------
    # When day cover is broken we flag every cell on that date that
    # *participates in* (D, D*) or *could/should have participated in* (*)
    # the day cover. The `*` is included because a sleepover-only assignment
    # that doesn't pair with proper day cover is a frequent cause of the
    # break (e.g. user changed a D* to * — the `*` is the smoking gun).
    DAY_COVER_AFFECTED = DAY_COVER_SHIFTS | {"*"}
    for d_str in day_strs:
        c_d = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "D")
        c_ds = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "D*")
        if c_d + c_ds != 2:
            affected = [{"date": d_str, "staff_initials": s} for s in staff_inits
                        if cell[(d_str, s)]["shift"] in DAY_COVER_AFFECTED]
            violations.append(_v("day_cover", "hard",
                f"Day cover is {c_d + c_ds} (need 2: 2D or D+D*)",
                date_=d_str, affected_cells=affected))
        if c_ds > 1:
            affected = [{"date": d_str, "staff_initials": s} for s in staff_inits
                        if cell[(d_str, s)]["shift"] == "D*"]
            violations.append(_v("day_cover", "hard",
                f"More than one D* on day cover ({c_ds})",
                date_=d_str, affected_cells=affected))

    # --- night_cover (immovable) -----------------------------------------
    # All three of N, D*, * participate in night cover so all are flagged
    # when night cover is broken.
    for d_str in day_strs:
        c_n = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "N")
        c_ds = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "D*")
        c_st = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "*")
        if c_n != 1:
            affected = [{"date": d_str, "staff_initials": s} for s in staff_inits
                        if cell[(d_str, s)]["shift"] in NIGHT_COVER_SHIFTS]
            violations.append(_v("night_cover", "hard",
                f"{c_n} waking-night staff (need exactly 1 N)",
                date_=d_str, affected_cells=affected))
        if c_ds + c_st != 1:
            affected = [{"date": d_str, "staff_initials": s} for s in staff_inits
                        if cell[(d_str, s)]["shift"] in NIGHT_COVER_SHIFTS]
            violations.append(_v("night_cover", "hard",
                f"{c_ds + c_st} sleepover staff (need exactly 1: D* or *)",
                date_=d_str, affected_cells=affected))

    # --- consecutive-day rules (immovable) -------------------------------
    for s in staff_inits:
        for i in range(len(day_strs) - 1):
            today = cell[(day_strs[i], s)]["shift"]
            tomorrow = cell[(day_strs[i + 1], s)]["shift"]
            if today == "N" and tomorrow == "D":
                violations.append(_v("no_n_to_d", "hard",
                    f"{s}: N → D between {day_strs[i]} and {day_strs[i+1]}",
                    date_=day_strs[i + 1], staff_initials=s,
                    affected_cells=[
                        {"date": day_strs[i], "staff_initials": s},
                        {"date": day_strs[i + 1], "staff_initials": s},
                    ]))
            if today == "D*" and tomorrow == "D*":
                violations.append(_v("no_dstar_to_dstar", "hard",
                    f"{s}: D* → D* between {day_strs[i]} and {day_strs[i+1]}",
                    date_=day_strs[i + 1], staff_initials=s,
                    affected_cells=[
                        {"date": day_strs[i], "staff_initials": s},
                        {"date": day_strs[i + 1], "staff_initials": s},
                    ]))
            if today in {"D*", "*"} and tomorrow in {"AL", "TRN"}:
                violations.append(_v("no_sleepover_before_leave", "hard",
                    f"{s}: {today} on {day_strs[i]} would extend into {tomorrow} on "
                    f"{day_strs[i+1]} — cannot sleepover straight into leave/training",
                    date_=day_strs[i], staff_initials=s,
                    affected_cells=[
                        {"date": day_strs[i], "staff_initials": s},
                        {"date": day_strs[i + 1], "staff_initials": s},
                    ]))

    # --- capability flags (immovable) ------------------------------------
    for d_str in day_strs:
        for s in staff_inits:
            sh = cell[(d_str, s)]["shift"]
            info = staff_by[s]
            if sh in {"D", "D*"} and not info.get("can_do_days"):
                violations.append(_v("capability_flags", "hard",
                    f"{s}: assigned {sh} but cannot do days",
                    date_=d_str, staff_initials=s))
            if sh == "N" and not info.get("can_do_nights"):
                violations.append(_v("capability_flags", "hard",
                    f"{s}: assigned N but cannot do nights",
                    date_=d_str, staff_initials=s))
            if sh in {"D*", "*"} and not info.get("can_do_sleepover"):
                violations.append(_v("capability_flags", "hard",
                    f"{s}: assigned {sh} but cannot sleepover",
                    date_=d_str, staff_initials=s))

    # --- locked cells preserved (immovable) ------------------------------
    # If a cell is locked, the validator just records it; we don't have the
    # "expected" value separately because the lock is on the cell itself.
    # This rule is enforced by the API (cell PATCH refuses if cell.locked).
    # Validator skips here.

    # --- per-shift med-competent + first-aider ---------------------------
    mode_med = _mode_for(rules_config, "med_competent_required", "hard")
    mode_fa  = _mode_for(rules_config, "first_aider_required", "hard")
    mode_pair = _mode_for(rules_config, "no_male_pair_alone", "hard")

    for d_str in day_strs:
        on_day = [s for s in staff_inits if cell[(d_str, s)]["shift"] in DAY_COVER_SHIFTS]
        on_night = [s for s in staff_inits if cell[(d_str, s)]["shift"] in NIGHT_COVER_SHIFTS]

        if mode_med != "off" and on_day and not any(staff_by[s].get("medication_competent") for s in on_day):
            violations.append(_v("med_competent_required", mode_med,
                "No medication-competent staff on day shift",
                date_=d_str,
                affected_cells=[{"date": d_str, "staff_initials": s} for s in on_day]))
        if mode_med != "off" and on_night and not any(staff_by[s].get("medication_competent") for s in on_night):
            violations.append(_v("med_competent_required", mode_med,
                "No medication-competent staff on night shift",
                date_=d_str,
                affected_cells=[{"date": d_str, "staff_initials": s} for s in on_night]))
        if mode_fa != "off" and on_day and not any(staff_by[s].get("first_aider") for s in on_day):
            violations.append(_v("first_aider_required", mode_fa,
                "No first-aider on day shift",
                date_=d_str,
                affected_cells=[{"date": d_str, "staff_initials": s} for s in on_day]))
        if mode_fa != "off" and on_night and not any(staff_by[s].get("first_aider") for s in on_night):
            violations.append(_v("first_aider_required", mode_fa,
                "No first-aider on night shift",
                date_=d_str,
                affected_cells=[{"date": d_str, "staff_initials": s} for s in on_night]))

        # Male-pair-alone
        if mode_pair != "off":
            males_day = [s for s in on_day if staff_by[s].get("gender") == "M"]
            females_day = [s for s in on_day if staff_by[s].get("gender") == "F"]
            if males_day and not females_day:
                violations.append(_v("no_male_pair_alone", mode_pair,
                    f"Day shift has only male staff ({', '.join(males_day)})",
                    date_=d_str,
                    affected_cells=[{"date": d_str, "staff_initials": s} for s in males_day]))
            males_night = [s for s in on_night if staff_by[s].get("gender") == "M"]
            females_night = [s for s in on_night if staff_by[s].get("gender") == "F"]
            if males_night and not females_night:
                violations.append(_v("no_male_pair_alone", mode_pair,
                    f"Night shift has only male staff ({', '.join(males_night)})",
                    date_=d_str,
                    affected_cells=[{"date": d_str, "staff_initials": s} for s in males_night]))

    # --- manager hard rule (is_admin_only or is_manager) ---------------
    mode_mgr = _mode_for(rules_config, "manager_no_shifts", "hard")
    if mode_mgr != "off":
        for s in staff_inits:
            info = staff_by[s]
            if not (info.get("is_admin_only") or info.get("is_manager")):
                continue
            for d_str in day_strs:
                cdat = cell[(d_str, s)]
                if cdat["shift"] in WORKING_SHIFTS and not cdat["locked"]:
                    violations.append(_v("manager_no_shifts", mode_mgr,
                        f"{s} (admin-only / manager) assigned {cdat['shift']} on {d_str} without manager override (lock)",
                        date_=d_str, staff_initials=s))

    # --- contracted hours minimum (PER WEEK) ----------------------------
    # Per-week check: for each staff S and each week W, total working hours
    # in W must be >= target_weekly_hours(S) - 12*AL_in_W - 8*TRN_in_W - 2.
    mode_hours = _mode_for(rules_config, "contracted_hours_min", "hard")
    if mode_hours != "off":
        for s in staff_inits:
            info = staff_by[s]
            target_weekly = int(info.get("target_weekly_hours", 0))
            if target_weekly <= 0:
                continue
            for w in range(weeks):
                week_strs = day_strs[w * 7:(w + 1) * 7]
                actual_w = 0
                al_w = 0
                trn_w = 0
                for d_str in week_strs:
                    sh = cell[(d_str, s)]["shift"]
                    actual_w += SHIFT_HOURS.get(sh, 0)
                    if sh == "AL":
                        al_w += 1
                    if sh == "TRN":
                        trn_w += 1
                min_required = target_weekly - 12 * al_w - 8 * trn_w - 2
                if actual_w < min_required:
                    violations.append(_v("contracted_hours_min", mode_hours,
                        f"{s}: week {w + 1} only {actual_w}h vs required ≥{min_required}h "
                        f"(target {target_weekly}/wk, AL {al_w}, TRN {trn_w})",
                        staff_initials=s, date_=week_strs[0],
                        affected_cells=[{"date": d, "staff_initials": s} for d in week_strs]))

    # --- senior_weekend_cover ------------------------------------------
    # For each Sat and Sun, at least one senior must be on D or D*.
    # De-hardcoded: derive from staff `is_senior` flag. Empty tuple
    # means rule self-disables (no seniors configured in this home).
    # AL exemption: skip when ALL flagged seniors are on AL/TRN that day.
    SENIOR_STAFF = tuple(s["initials"] for s in staff if s.get("is_senior"))
    mode_sw = _mode_for(rules_config, "senior_weekend_cover", "hard")
    present_seniors = [s for s in SENIOR_STAFF if s in staff_by]
    if mode_sw != "off" and present_seniors:
        for di, d_str in enumerate(day_strs):
            dow = (_parse_date(d_str).weekday())
            if dow < 5:
                continue
            avail_seniors = [s for s in present_seniors
                             if cell[(d_str, s)]["shift"] not in {"AL", "TRN"}]
            if not avail_seniors:
                continue  # both seniors on AL/TRN — rule unsatisfiable, skip
            on_cover = [s for s in avail_seniors
                        if cell[(d_str, s)]["shift"] in {"D", "D*"}]
            if not on_cover:
                violations.append(_v("senior_weekend_cover", mode_sw,
                    f"No senior ({' or '.join(avail_seniors)}) on day cover "
                    f"on {d_str} ({DOW_NAMES[dow]})",
                    date_=d_str,
                    affected_cells=[{"date": d_str, "staff_initials": s}
                                    for s in avail_seniors]))

    # --- avoid_pair_seniors --------------------------------------------
    # Soft penalty-style violation when the two flagged seniors are both
    # on day cover (D or D*) on the same date. Only fires when at least
    # 2 seniors are flagged (is_senior=True) — otherwise there's no pair.
    mode_aps = _mode_for(rules_config, "avoid_pair_seniors", "soft")
    if mode_aps != "off" and len(present_seniors) >= 2:
        a, b = present_seniors[0], present_seniors[1]
        for d_str in day_strs:
            a_shift = cell[(d_str, a)]["shift"]
            b_shift = cell[(d_str, b)]["shift"]
            if a_shift in {"D", "D*"} and b_shift in {"D", "D*"}:
                violations.append(_v("avoid_pair_seniors", mode_aps,
                    f"{a} and {b} both on day cover on {d_str} "
                    "— manager prefers to split seniors",
                    date_=d_str,
                    affected_cells=[
                        {"date": d_str, "staff_initials": a},
                        {"date": d_str, "staff_initials": b},
                    ]))

    # --- max_one_per_role_on_al ----------------------------------------
    # Two staff sharing the same role (e.g. two Flexi) cannot be on AL on
    # the same date. Single-occupant roles trivially satisfy.
    mode_mra = _mode_for(rules_config, "max_one_per_role_on_al", "hard")
    if mode_mra != "off":
        # Group staff by role
        role_staff: dict[str, list[str]] = {}
        for s in staff:
            role = s.get("role")
            if not role:
                continue
            role_staff.setdefault(role, []).append(s["initials"])
        # For each date and each role with >1 occupant, count AL
        for d_str in day_strs:
            for role, inits in role_staff.items():
                if len(inits) < 2:
                    continue
                on_al = [i for i in inits if cell[(d_str, i)]["shift"] == "AL"]
                if len(on_al) > 1:
                    violations.append(_v("max_one_per_role_on_al", mode_mra,
                        f"{', '.join(on_al)} ({role}) all on AL on {d_str} "
                        "— max 1 per role per day",
                        date_=d_str,
                        affected_cells=[{"date": d_str, "staff_initials": i}
                                        for i in on_al]))

    # --- min_sleepover_per_week_for_seniors ----------------------------
    # New params shape: {rules: [{staff_initials: [...], min_per_week: N}, ...]}
    msl_mode = _mode_for(rules_config, "min_sleepover_per_week_for_seniors", "soft")
    if msl_mode != "off":
        msl_entry = (rules_config or {}).get("min_sleepover_per_week_for_seniors") or {}
        msl_params = msl_entry.get("params") if isinstance(msl_entry, dict) else {}
        msl_params = msl_params or {}
        if "rules" in msl_params:
            msl_rules = msl_params.get("rules") or []
        else:
            legacy_inits = (
                msl_params.get("staff_initials")
                or [s["initials"] for s in staff if s.get("is_senior")]
            )
            msl_rules = [{
                "staff_initials": legacy_inits,
                "min_per_week": msl_params.get("min_sleepovers_per_week", 1),
            }]
        for rule_entry in msl_rules:
            min_n = max(0, int(rule_entry.get("min_per_week", 1)))
            if min_n <= 0:
                continue
            entry_staff = [s for s in (rule_entry.get("staff_initials") or [])
                           if s in staff_by]
            for s in entry_staff:
                for w in range(weeks):
                    week_strs = day_strs[w * 7:(w + 1) * 7]
                    dstar_w = sum(1 for d in week_strs if cell[(d, s)]["shift"] == "D*")
                    unavail_w = sum(
                        1 for d in week_strs
                        if cell[(d, s)]["shift"] in {"AL", "TRN"}
                    )
                    # AL exemption: skip when staff has >=3 AL/TRN days that week.
                    if unavail_w >= 3:
                        continue
                    # Scale required min by unavail (rough heuristic: each
                    # pair of unavail days knocks 1 off the required min).
                    eff_min = max(0, min_n - (unavail_w // 2))
                    if eff_min <= 0:
                        continue
                    if dstar_w < eff_min:
                        violations.append(_v("min_sleepover_per_week_for_seniors", msl_mode,
                            f"{s}: only {dstar_w} D* in week {w + 1} (need ≥{eff_min}"
                            + (f", scaled from {min_n} for {unavail_w} AL/TRN day(s)" if eff_min != min_n else "")
                            + ")",
                            staff_initials=s, date_=week_strs[0],
                            affected_cells=[{"date": d, "staff_initials": s}
                                            for d in week_strs]))

    # --- senior_monday_cover ------------------------------------------
    smc_mode = _mode_for(rules_config, "senior_monday_cover", "soft")
    if smc_mode != "off":
        smc_entry = (rules_config or {}).get("senior_monday_cover") or {}
        smc_params = smc_entry.get("params") if isinstance(smc_entry, dict) else {}
        smc_params = smc_params or {}
        smc_default = [s["initials"] for s in staff if s.get("is_senior")]
        smc_staff = [s for s in (smc_params.get("staff_initials") or smc_default)
                     if s in staff_by]
        if smc_staff:
            for di, d_str in enumerate(day_strs):
                if _parse_date(d_str).weekday() != 0:  # not Monday
                    continue
                # AL exemption: skip when ALL configured senior staff are
                # forced unavailable that Monday.
                avail_smc = [s for s in smc_staff
                             if cell[(d_str, s)]["shift"] not in {"AL", "TRN"}]
                if not avail_smc:
                    continue
                covered = [s for s in avail_smc
                           if cell[(d_str, s)]["shift"] in {"D", "D*"}]
                if not covered:
                    violations.append(_v("senior_monday_cover", smc_mode,
                        f"No senior ({' or '.join(avail_smc)}) on day cover "
                        f"on Monday {d_str}",
                        date_=d_str,
                        affected_cells=[{"date": d_str, "staff_initials": s}
                                        for s in avail_smc]))

    # --- respect_shift_preference -------------------------------------
    rsp_mode = _mode_for(rules_config, "respect_shift_preference", "soft")
    if rsp_mode != "off":
        for s in staff_inits:
            info = staff_by[s]
            if not (info.get("can_do_days") and info.get("can_do_nights")):
                continue
            pref = (info.get("shift_preference") or "no_preference").lower()
            if pref not in {"day", "night"}:
                continue
            off_pref = {"N", "*"} if pref == "day" else {"D", "D*"}
            for d_str in day_strs:
                shift = cell[(d_str, s)]["shift"]
                if shift in off_pref:
                    violations.append(_v("respect_shift_preference", rsp_mode,
                        f"{s} on {shift} on {d_str} but prefers {pref}s",
                        staff_initials=s, date_=d_str,
                        affected_cells=[{"date": d_str, "staff_initials": s}]))

    # --- avoid_star_then_night & avoid_star_then_day -----------------
    asn_mode = _mode_for(rules_config, "avoid_star_then_night", "soft")
    asd_mode = _mode_for(rules_config, "avoid_star_then_day", "soft")
    if asn_mode != "off" or asd_mode != "off":
        asd_entry = (rules_config or {}).get("avoid_star_then_day") or {}
        asd_params = asd_entry.get("params") if isinstance(asd_entry, dict) else {}
        asd_params = asd_params or {}
        senior_overrides = {s["initials"]: 60 for s in staff if s.get("is_senior")}
        asd_overrides = asd_params.get("staff_overrides") or senior_overrides
        for s in staff_inits:
            for i in range(len(day_strs) - 1):
                today_d = day_strs[i]
                tomorrow_d = day_strs[i + 1]
                today = cell[(today_d, s)]["shift"]
                tomorrow = cell[(tomorrow_d, s)]["shift"]
                if today != "*":
                    continue
                if tomorrow == "N" and asn_mode != "off":
                    violations.append(_v("avoid_star_then_night", asn_mode,
                        f"{s}: * on {today_d} -> N on {tomorrow_d} "
                        "(general avoid pattern)",
                        date_=today_d, staff_initials=s,
                        affected_cells=[
                            {"date": today_d, "staff_initials": s},
                            {"date": tomorrow_d, "staff_initials": s},
                        ]))
                if tomorrow == "D" and asd_mode != "off":
                    is_override = s in asd_overrides
                    msg_tail = (
                        f"(strong-avoid pattern for {s})" if is_override
                        else "(general avoid pattern)"
                    )
                    violations.append(_v("avoid_star_then_day", asd_mode,
                        f"{s}: * on {today_d} -> D on {tomorrow_d} {msg_tail}",
                        date_=today_d, staff_initials=s,
                        affected_cells=[
                            {"date": today_d, "staff_initials": s},
                            {"date": tomorrow_d, "staff_initials": s},
                        ]))

    # --- avoid_star_for_staff -----------------------------------------
    asfs_mode = _mode_for(rules_config, "avoid_star_for_staff", "soft")
    asfs_staff: list[str] = []
    if asfs_mode != "off":
        asfs_entry = (rules_config or {}).get("avoid_star_for_staff") or {}
        asfs_params = asfs_entry.get("params") if isinstance(asfs_entry, dict) else {}
        asfs_params = asfs_params or {}
        asfs_default = [s["initials"] for s in staff if s.get("is_senior")]
        asfs_staff = [s for s in (asfs_params.get("staff_initials") or asfs_default)
                      if s in staff_by]
        for s in asfs_staff:
            for d_str in day_strs:
                if cell[(d_str, s)]["shift"] == "*":
                    violations.append(_v("avoid_star_for_staff", asfs_mode,
                        f"{s}: assigned `*` (sleepover-only) on {d_str} — "
                        f"{s} prefers D or D* over bare *",
                        date_=d_str, staff_initials=s,
                        affected_cells=[{"date": d_str, "staff_initials": s}]))

    # --- max_sleepover_per_week --------------------------------------
    msx_mode = _mode_for(rules_config, "max_sleepover_per_week", "soft")
    if msx_mode != "off":
        msx_entry = (rules_config or {}).get("max_sleepover_per_week") or {}
        msx_params = msx_entry.get("params") if isinstance(msx_entry, dict) else {}
        msx_params = msx_params or {}
        for rule_entry in (msx_params.get("rules") or []):
            cap = rule_entry.get("max_per_week")
            if cap is None:
                continue
            cap = int(cap)
            entry_staff = [s for s in (rule_entry.get("staff_initials") or [])
                           if s in staff_by]
            for s in entry_staff:
                for w in range(weeks):
                    week_strs = day_strs[w * 7:(w + 1) * 7]
                    dstars = sum(1 for d in week_strs if cell[(d, s)]["shift"] == "D*")
                    if dstars > cap:
                        violations.append(_v("max_sleepover_per_week", msx_mode,
                            f"{s}: {dstars} D* in week {w + 1} (max {cap})",
                            date_=week_strs[0], staff_initials=s,
                            affected_cells=[{"date": d, "staff_initials": s}
                                            for d in week_strs
                                            if cell[(d, s)]["shift"] == "D*"]))

    # --- fair_star_distribution ---------------------------------------
    fsd_mode = _mode_for(rules_config, "fair_star_distribution", "soft")
    if fsd_mode != "off":
        avoid_set = set(asfs_staff)  # populated in the avoid_star_for_staff block above
        eligible = [
            s for s in staff_inits
            if staff_by[s].get("can_do_sleepover") and s not in avoid_set
        ]
        if len(eligible) >= 2:
            counts = {
                s: sum(1 for d in day_strs if cell[(d, s)]["shift"] == "*")
                for s in eligible
            }
            spread = max(counts.values()) - min(counts.values())
            if spread > 2:
                violations.append(_v("fair_star_distribution", fsd_mode,
                    f"Uneven `*` distribution across eligible staff: "
                    f"{counts} (spread {spread} > 2)",
                    affected_cells=[]))

    # --- weekday_weekend_split ----------------------------------------
    wws_mode = _mode_for(rules_config, "weekday_weekend_split", "soft")
    if wws_mode != "off":
        wws_entry = (rules_config or {}).get("weekday_weekend_split") or {}
        wws_params = wws_entry.get("params") if isinstance(wws_entry, dict) else {}
        wws_params = wws_params or {}
        for rule_entry in (wws_params.get("rules") or []):
            wd_target = int(rule_entry.get("weekday_target", 1))
            we_target = int(rule_entry.get("weekend_target", 1))
            shift_types = set(rule_entry.get("shift_types") or ["N"])
            entry_inits = rule_entry.get("staff_initials")
            if isinstance(entry_inits, str):
                entry_staff = [entry_inits] if entry_inits in staff_by else []
            else:
                entry_staff = [s for s in (entry_inits or []) if s in staff_by]
            for s in entry_staff:
                for w in range(weeks):
                    week_strs = day_strs[w * 7:(w + 1) * 7]
                    weekday_n = 0
                    weekend_n = 0
                    weekday_avail = 0
                    weekend_avail = 0
                    for d_str in week_strs:
                        sh = cell[(d_str, s)]["shift"]
                        is_weekend = _parse_date(d_str).weekday() >= 5
                        # AL exemption: count only days where staff is NOT
                        # forced unavailable (AL/TRN). Empty sub-windows
                        # are skipped entirely.
                        if sh in {"AL", "TRN"}:
                            continue
                        if is_weekend:
                            weekend_avail += 1
                        else:
                            weekday_avail += 1
                        if sh not in shift_types:
                            continue
                        if is_weekend:
                            weekend_n += 1
                        else:
                            weekday_n += 1
                    # Skip the rule entirely when both sub-windows are empty
                    # (full-week AL/TRN). Otherwise only flag if the available
                    # sub-window's count differs from target.
                    weekday_off_target = weekday_avail > 0 and weekday_n != wd_target
                    weekend_off_target = weekend_avail > 0 and weekend_n != we_target
                    if weekday_off_target or weekend_off_target:
                        violations.append(_v("weekday_weekend_split", wws_mode,
                            f"{s}: week {w + 1} has {weekday_n} weekday + {weekend_n} weekend "
                            f"{'/'.join(sorted(shift_types))} (target {wd_target}/{we_target})",
                            staff_initials=s, date_=week_strs[0],
                            affected_cells=[
                                {"date": d, "staff_initials": s}
                                for d in week_strs
                                if cell[(d, s)]["shift"] in shift_types
                            ]))

    # --- pair_companion_on_day ----------------------------------------
    pco_mode = _mode_for(rules_config, "pair_companion_on_day", "soft")
    if pco_mode != "off":
        pco_entry = (rules_config or {}).get("pair_companion_on_day") or {}
        pco_params = pco_entry.get("params") if isinstance(pco_entry, dict) else {}
        pco_params = pco_params or {}
        for rule_entry in (pco_params.get("rules") or []):
            focal = rule_entry.get("staff_initials")
            if isinstance(focal, list):
                focal = focal[0] if focal else None
            if not focal or focal not in staff_by:
                continue
            companions = [c for c in (rule_entry.get("companion_initials") or [])
                          if c in staff_by and c != focal]
            if not companions:
                continue
            target_dow = _normalise_dow(rule_entry.get("day_of_week", "Wed"))
            if target_dow is None:
                continue
            shift_types_set = set(rule_entry.get("shift_types") or ["D", "D*"])
            for d_str in day_strs:
                if _parse_date(d_str).weekday() != target_dow:
                    continue
                # AL exemption #1: focal on AL/TRN
                focal_shift = cell[(d_str, focal)]["shift"]
                if focal_shift in {"AL", "TRN"}:
                    continue
                # AL exemption #2: all companions on AL/TRN
                avail_companions = [c for c in companions
                                    if cell[(d_str, c)]["shift"] not in {"AL", "TRN"}]
                if not avail_companions:
                    continue
                if focal_shift not in shift_types_set:
                    continue  # focal not on a triggering shift — rule doesn't apply
                companion_present = [c for c in avail_companions
                                     if cell[(d_str, c)]["shift"] in shift_types_set]
                if not companion_present:
                    violations.append(_v("pair_companion_on_day", pco_mode,
                        f"{focal} on {focal_shift} on {DOW_NAMES[target_dow]} {d_str} "
                        f"with no companion ({', '.join(avail_companions)}) on a working "
                        f"day shift",
                        date_=d_str, staff_initials=focal,
                        affected_cells=[{"date": d_str, "staff_initials": focal}]
                            + [{"date": d_str, "staff_initials": c} for c in avail_companions]))

    # --- avoid_staff_pairs (multi-pair) -------------------------------
    # New rule: manager-configured list of staff pairs who should not share
    # day cover. Fires per (pair, date) when both are on D/D*.
    asp_mode = _mode_for(rules_config, "avoid_staff_pairs", "soft")
    asp_entry = (rules_config or {}).get("avoid_staff_pairs") or {}
    asp_params = asp_entry.get("params") if isinstance(asp_entry, dict) else {}
    asp_params = asp_params or {}
    if asp_mode != "off":
        pairs = asp_params.get("pairs") or []
        for p in pairs:
            a = p.get("staff_a_initials") or p.get("a")
            b = p.get("staff_b_initials") or p.get("b")
            if not (a and b and a != b and a in staff_by and b in staff_by):
                continue
            for d_str in day_strs:
                a_shift = cell[(d_str, a)]["shift"]
                b_shift = cell[(d_str, b)]["shift"]
                if a_shift in {"D", "D*"} and b_shift in {"D", "D*"}:
                    violations.append(_v("avoid_staff_pairs", asp_mode,
                        f"{a} and {b} both on day cover on {d_str} "
                        "— manager-configured pair should not share day cover",
                        date_=d_str,
                        affected_cells=[
                            {"date": d_str, "staff_initials": a},
                            {"date": d_str, "staff_initials": b},
                        ]))

    # --- weekend_off_per_rota -----------------------------------------
    # Every staff should have ≥1 full weekend (Sat+Sun) off per rota.
    wofr_mode = _mode_for(rules_config, "weekend_off_per_rota", "soft")
    if wofr_mode != "off":
        # Collect Sat/Sun pairs.
        pairs_dates: list[tuple[str, str]] = []
        for i, d_str in enumerate(day_strs[:-1]):
            if DOW_IDX.get(d_str) == 5 and DOW_IDX.get(day_strs[i + 1]) == 6:
                pairs_dates.append((d_str, day_strs[i + 1]))
        if pairs_dates:
            OFF_TYPES = {"OFF", "AL", "TRN"}
            for s in staff_inits:
                # Exempt staff forced AL/TRN every weekend day.
                all_unavail = all(
                    cell[(sat, s)]["shift"] in {"AL", "TRN"}
                    and cell[(sun, s)]["shift"] in {"AL", "TRN"}
                    for sat, sun in pairs_dates
                )
                if all_unavail:
                    continue
                has_full_off = any(
                    cell[(sat, s)]["shift"] in OFF_TYPES
                    and cell[(sun, s)]["shift"] in OFF_TYPES
                    for sat, sun in pairs_dates
                )
                if not has_full_off:
                    violations.append(_v("weekend_off_per_rota", wofr_mode,
                        f"{s} has no full weekend off in the rota",
                        staff_initials=s))

    return violations


def summarise_violations(violations: list[dict]) -> dict:
    hard = sum(1 for v in violations if v["severity"] == "hard")
    soft = sum(1 for v in violations if v["severity"] == "soft")
    return {"total": len(violations), "hard": hard, "soft": soft}
