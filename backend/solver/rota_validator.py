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
    for d_str in day_strs:
        c_d = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "D")
        c_ds = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "D*")
        if c_d + c_ds != 2:
            affected = [{"date": d_str, "staff_initials": s} for s in staff_inits
                        if cell[(d_str, s)]["shift"] in DAY_COVER_SHIFTS]
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
    for d_str in day_strs:
        c_n = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "N")
        c_ds = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "D*")
        c_st = sum(1 for s in staff_inits if cell[(d_str, s)]["shift"] == "*")
        if c_n != 1:
            affected = [{"date": d_str, "staff_initials": s} for s in staff_inits
                        if cell[(d_str, s)]["shift"] == "N"]
            violations.append(_v("night_cover", "hard",
                f"{c_n} waking-night staff (need exactly 1 N)",
                date_=d_str, affected_cells=affected))
        if c_ds + c_st != 1:
            affected = [{"date": d_str, "staff_initials": s} for s in staff_inits
                        if cell[(d_str, s)]["shift"] in {"D*", "*"}]
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

    # --- manager hard rule (J.C.) ---------------------------------------
    mode_mgr = _mode_for(rules_config, "manager_no_shifts", "hard")
    if mode_mgr != "off":
        for s in staff_inits:
            if not staff_by[s].get("is_admin_only"):
                continue
            for d_str in day_strs:
                cdat = cell[(d_str, s)]
                if cdat["shift"] in WORKING_SHIFTS and not cdat["locked"]:
                    violations.append(_v("manager_no_shifts", mode_mgr,
                        f"{s} (admin-only) assigned {cdat['shift']} on {d_str} without manager override (lock)",
                        date_=d_str, staff_initials=s))

    # --- contracted hours minimum ---------------------------------------
    mode_hours = _mode_for(rules_config, "contracted_hours_min", "hard")
    if mode_hours != "off":
        for s in staff_inits:
            info = staff_by[s]
            target_total = int(info.get("target_weekly_hours", 0)) * weeks
            if target_total <= 0:
                continue
            actual = 0
            al_count = 0
            trn_count = 0
            for d_str in day_strs:
                sh = cell[(d_str, s)]["shift"]
                actual += SHIFT_HOURS.get(sh, 0)
                if sh == "AL":
                    al_count += 1
                if sh == "TRN":
                    trn_count += 1
            min_required = target_total - 12 * al_count - 8 * trn_count - 2
            if actual < min_required:
                violations.append(_v("contracted_hours_min", mode_hours,
                    f"{s}: only {actual}h scheduled vs required ≥{min_required}h "
                    f"(target {target_total}, AL {al_count}, TRN {trn_count})",
                    staff_initials=s,
                    affected_cells=[{"date": d, "staff_initials": s} for d in day_strs]))

    return violations


def summarise_violations(violations: list[dict]) -> dict:
    hard = sum(1 for v in violations if v["severity"] == "hard")
    soft = sum(1 for v in violations if v["severity"] == "soft")
    return {"total": len(violations), "hard": hard, "soft": soft}
