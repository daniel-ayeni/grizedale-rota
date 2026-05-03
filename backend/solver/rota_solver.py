"""
Grizedale Rota Solver — Phase 1
================================

Updates from Phase 0 (per user feedback):
    - **Hard** rule: Manager (J.C., is_admin_only=True) cannot be assigned
      D, D*, N or * unless that cell is in `locked_cells`. (Was a soft penalty.)
    - **Relaxed** night medication rule: at least ONE of the three night
      staff (D*, *, N) must be medication-competent. It does NOT have to
      be the waking-night staff specifically.
    - **New hard** rule: every staff's total scheduled hours must be
      >= (target_weekly_hours × weeks) − (AL_days × 12) − (TRN_days × 8) − 2.
      Staff with target_weekly_hours == 0 (e.g. J.C.) are excluded.
    - **New soft** rule: sleepover-capable staff prefer D* over D
      (penalty 5 per `D` assignment for those staff).

Each rule's mode (hard / soft / off) can be overridden per request via
`payload["rules"]` — values are either booleans (legacy) or strings.

Rule keys understood:
    first_aider_required          hard|soft|off  (default: hard)
    med_competent_required        hard|soft|off  (default: hard)
    no_male_pair_alone            hard|soft|off  (default: hard)
    manager_no_shifts             hard|soft|off  (default: hard)
    contracted_hours_min          hard|soft|off  (default: hard)
    sleepover_preference          hard|soft|off  (default: soft)
    preferred_off_days            hard|soft|off  (default: soft)
    avoid_pairs                   hard|soft|off  (default: soft)
    weekend_fairness              hard|soft|off  (default: soft)

Soft-rule weights can be tuned via `payload["rule_weights"]` (numeric).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

from ortools.sat.python import cp_model


SHIFT_TYPES = ["D", "D*", "N", "*", "OFF", "AL", "TRN"]
WORKING_SHIFTS = {"D", "D*", "N", "*"}
DAY_COVER_SHIFTS = {"D", "D*"}
NIGHT_COVER_SHIFTS = {"N", "D*", "*"}

DEFAULT_SHIFT_HOURS = {
    "D": 12,
    "D*": 14,
    "N": 12,
    "*": 0,
    "OFF": 0,
    "AL": 0,
    "TRN": 0,
}

DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DEFAULT_WEIGHTS = {
    "manager_no_shifts": 100_000,        # only used if rule is "soft"
    "first_aider_required": 5_000,
    "med_competent_required": 5_000,
    "no_male_pair_alone": 5_000,
    "contracted_hours_min": 50,          # only used if rule is "soft"
    "sleepover_preference": 5,
    "preferred_off_days": 20,
    "avoid_pairs": 30,
    "weekend_fairness": 10,
    "hours_overage": 5,                  # always-on small penalty for over-target (flexi only)
    "overtime_prefer_flexi": 15,         # reward (negative) per hour for flexi overtime
    "non_flexi_overage": 50,             # STRONG penalty for non-flexi over contracted
    "prefer_dstar_over_star": 200,       # penalty per day where * is used instead of D*
    "senior_weekend_cover": 5_000,       # only used if rule is "soft"
    "senior_weekend_rotation_nudge": 30, # reward for assigned senior being on D/D* their weekend
    "avoid_pair_seniors": 40,            # penalty per day L.M. + L.D. both on day cover
    "min_sleepover_per_week_for_seniors": 400,  # penalty per missing D* per staff per week
                                                # (must exceed ~300 = +2h × opt-out(150)/h on
                                                # the staff being "promoted" to a D*)
    "senior_monday_cover": 60,                  # penalty per Monday with no senior on shift
    "respect_shift_preference": 80,             # penalty per off-preference shift
    "avoid_star_then_night": 25,                # penalty per (*,N) consecutive pair
    "avoid_star_then_day": 20,                  # general penalty per (*,D) pair (L.D. overridden)
    "avoid_star_for_staff": 50,                 # penalty per `*` shift for listed staff
    "max_sleepover_per_week": 80,               # penalty per D* over the per-week cap
    "fair_star_distribution": 30,               # penalty per unit of (max − min) `*` count across eligibles
    "weekday_weekend_split": 40,                # penalty per unit of |actual - target| weekday or weekend count
    "pair_companion_on_day": 200,               # penalty per (focal works alone) day
    "avoid_staff_pairs": 40,                    # penalty per day listed pair of staff both on day cover
    "weekend_off_per_rota": 50,                 # penalty per staff with 0 full-weekends-off
}

DEFAULT_RULE_MODES = {
    "first_aider_required": "hard",
    "med_competent_required": "hard",
    "no_male_pair_alone": "hard",
    "manager_no_shifts": "hard",
    "contracted_hours_min": "hard",
    "sleepover_preference": "soft",
    "preferred_off_days": "soft",
    "avoid_pairs": "soft",
    "weekend_fairness": "soft",
    "overtime_prefer_flexi": "soft",
    "prefer_dstar_over_star": "soft",
    "non_flexi_overage": "soft",
    "senior_weekend_cover": "hard",
    "avoid_pair_seniors": "soft",
    "min_sleepover_per_week_for_seniors": "soft",
    "senior_monday_cover": "soft",
    "respect_shift_preference": "soft",
    "avoid_star_then_night": "soft",
    "avoid_star_then_day": "soft",
    "avoid_star_for_staff": "soft",
    "max_sleepover_per_week": "soft",
    "fair_star_distribution": "soft",
    "weekday_weekend_split": "soft",
    "pair_companion_on_day": "soft",
    "avoid_staff_pairs": "soft",
    "weekend_off_per_rota": "soft",
}

# ---------------------------------------------------------------------------
# Role-flag derivation — all "who counts as a senior / flexi / night / admin"
# lookups flow from the per-staff role flags (is_senior, is_flexi, is_night,
# is_manager, is_admin_only). This keeps the solver free of ANY hard-coded
# staff initials. Managers toggle the flags on /staff and the solver picks
# up the changes on the next solve. Empty fallback = rule simply doesn't
# apply when no staff carries the flag.


def _derive_role_staff(staff_list: list[dict], flag: str) -> tuple[str, ...]:
    """Return the initials of every staff member carrying `flag=True`.

    Example:
        _derive_role_staff(staff_list, "is_senior") → initials of all
        staff the manager has flagged as senior.

    An empty tuple is returned when no staff carries the flag; the calling
    rule then self-disables (no-op) instead of applying to a hard-coded
    default, so the solver never references nonexistent staff.
    """
    return tuple(s["initials"] for s in staff_list if s.get(flag))

DOW_FROM_STR = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _normalise_dow(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and 0 <= value <= 6:
        return value
    if isinstance(value, str):
        return DOW_FROM_STR.get(value.strip().lower()[:3])
    return None


# ---------------------------------------------------------------------------
def _date_range(start: date, weeks: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(weeks * 7)]


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _normalise_mode(value: Any, default: str) -> str:
    """Accept legacy bool or string ('hard'|'soft'|'off')."""
    if value is True:
        return default if default != "off" else "hard"
    if value is False:
        return "off"
    if isinstance(value, str) and value.lower() in {"hard", "soft", "off"}:
        return value.lower()
    return default


def _resolve_modes(rules: dict | None) -> dict[str, str]:
    rules = rules or {}
    out = {}
    for k, default in DEFAULT_RULE_MODES.items():
        out[k] = _normalise_mode(rules.get(k), default)
    return out


def _resolve_weights(weights: dict | None) -> dict[str, int]:
    out = dict(DEFAULT_WEIGHTS)
    for k, v in (weights or {}).items():
        if isinstance(v, (int, float)):
            out[k] = int(v)
    return out


# ---------------------------------------------------------------------------
def solve_rota(payload: dict[str, Any], time_limit_s: int = 10) -> dict[str, Any]:
    started = time.time()

    start_date = _parse_date(payload["rota_start_date"])
    weeks = int(payload.get("weeks", 4))
    days = _date_range(start_date, weeks)
    n_days = len(days)

    staff_list = payload["staff"]
    staff_by = {s["initials"]: s for s in staff_list}
    staff_inits = [s["initials"] for s in staff_list]

    modes = _resolve_modes(payload.get("rules"))
    weights = _resolve_weights(payload.get("rule_weights"))
    rule_params = payload.get("rule_params") or {}
    shift_hours = dict(DEFAULT_SHIFT_HOURS)
    shift_hours.update(payload.get("shift_hours", {}) or {})

    leave = payload.get("leave", []) or []
    locked_cells = payload.get("locked_cells", []) or []
    avoid_pairs = payload.get("avoid_pairs", []) or []

    # Forced cells indexed by (initials, date_str) -> shift
    forced_cells: dict[tuple[str, str], str] = {}
    for e in leave:
        forced_cells[(e["staff_initials"], e["date"])] = e.get("type", "AL")
    for e in locked_cells:
        forced_cells[(e["staff_initials"], e["date"])] = e["shift"]

    # ── AL/TRN-aware helpers ──────────────────────────────────────────────
    # `_unavail` and `_unavail_in_week` answer "is the staff forced unavailable
    # (AL/TRN) on this date / how many days in this week?" Used by every per-
    # week / per-day soft rule below to short-circuit so AL doesn't trigger
    # spurious violations (J.R. on AL all w2 must NOT trip min-hours, weekday/
    # weekend split, etc.).
    def _is_forced_unavail(s: str, di: int) -> bool:
        return forced_cells.get((s, days[di].isoformat())) in {"AL", "TRN"}

    def _unavail_count_in_week(s: str, w: int) -> int:
        return sum(1 for di in range(w * 7, (w + 1) * 7) if _is_forced_unavail(s, di))

    model = cp_model.CpModel()

    # x[s][di][t]
    x: dict[str, dict[int, dict[str, cp_model.IntVar]]] = {}
    for s in staff_inits:
        x[s] = {}
        for di in range(n_days):
            x[s][di] = {t: model.NewBoolVar(f"x_{s}_{di}_{t}") for t in SHIFT_TYPES}
            model.Add(sum(x[s][di][t] for t in SHIFT_TYPES) == 1)

    # Capability flags
    for s in staff_inits:
        info = staff_by[s]
        for di in range(n_days):
            if not info.get("can_do_days"):
                model.Add(x[s][di]["D"] == 0)
            if not info.get("can_do_sleepover"):
                model.Add(x[s][di]["D*"] == 0)
                model.Add(x[s][di]["*"] == 0)
            elif not info.get("can_do_days"):
                model.Add(x[s][di]["D*"] == 0)
            if not info.get("can_do_nights"):
                model.Add(x[s][di]["N"] == 0)

    # Forced cells (locked / AL / TRN)
    for (init, d_str), shift in forced_cells.items():
        if init not in staff_by or shift not in SHIFT_TYPES:
            continue
        try:
            di = days.index(_parse_date(d_str))
        except ValueError:
            continue
        for t in SHIFT_TYPES:
            model.Add(x[init][di][t] == (1 if t == shift else 0))

    # AL and TRN are operator-driven only — solver may not choose them
    # voluntarily. (Without this, the solver could assign AL to relax the
    # contracted-hours hard rule.)
    for s in staff_inits:
        for di in range(n_days):
            d_str = days[di].isoformat()
            forced = forced_cells.get((s, d_str))
            if forced != "AL":
                model.Add(x[s][di]["AL"] == 0)
            if forced != "TRN":
                model.Add(x[s][di]["TRN"] == 0)

    # Manager hard rule: any staff flagged `is_admin_only` or `is_manager`
    # cannot work shifts unless the cell is explicitly locked. This fires
    # off the per-staff role flag (set on /staff) so ANY staff can be
    # promoted to Manager without code changes.
    if modes["manager_no_shifts"] == "hard":
        for s in staff_inits:
            info = staff_by[s]
            if not (info.get("is_admin_only") or info.get("is_manager")):
                continue
            for di in range(n_days):
                d_str = days[di].isoformat()
                if (s, d_str) in forced_cells:
                    continue  # locked override allowed
                for t in WORKING_SHIFTS:
                    model.Add(x[s][di][t] == 0)

    # Daily cover constraints — count is configurable via settings
    # (`day_cover_count` / `night_cover_count`) and per-date via
    # `cover_overrides: [{date, day_count, night_count}]`. Defaults
    # preserve the long-running 2D/2N behaviour.
    global_day_count = int(payload.get("day_cover_count") or 2)
    global_night_count = int(payload.get("night_cover_count") or 2)
    cover_overrides_raw = payload.get("cover_overrides") or []
    cover_override_by_date: dict[str, dict] = {}
    for ov in cover_overrides_raw:
        d = ov.get("date")
        if d:
            cover_override_by_date[d] = ov

    for di in range(n_days):
        d_str = days[di].isoformat()
        ov = cover_override_by_date.get(d_str) or {}
        day_count = int(ov.get("day_count", global_day_count))
        night_count = int(ov.get("night_count", global_night_count))
        # Defensive clamp — solver needs at least 1 of each.
        day_count = max(1, day_count)
        night_count = max(1, night_count)

        cD = sum(x[s][di]["D"] for s in staff_inits)
        cDs = sum(x[s][di]["D*"] for s in staff_inits)
        cN = sum(x[s][di]["N"] for s in staff_inits)
        cStar = sum(x[s][di]["*"] for s in staff_inits)

        # Day cover: exactly `day_count` staff on D / D*; D* limited to 1
        # (only one sleepover-day counts against day cover).
        model.Add(cD + cDs == day_count)
        model.Add(cDs <= 1)
        # Night cover: sum of (waking N) + (D* or * sleepover) == night_count.
        # We keep exactly one sleepover (D* or *) — the "waking" remainder
        # is night_count - 1 N shifts.
        model.Add(cN == night_count - 1)
        model.Add(cDs + cStar == 1)

    # Per-shift med-competent + first-aider
    soft_terms: list[cp_model.IntVar | int] = []
    med_staff = [s for s in staff_inits if staff_by[s].get("medication_competent")]
    fa_staff = [s for s in staff_inits if staff_by[s].get("first_aider")]
    males = [s for s in staff_inits if staff_by[s].get("gender") == "M"]
    females = [s for s in staff_inits if staff_by[s].get("gender") == "F"]

    for di in range(n_days):
        # Day-shift med (sum over D + D* of med staff)
        med_day = sum(x[s][di]["D"] + x[s][di]["D*"] for s in med_staff)
        # Night-shift med — RELAXED: any of N, D*, *
        med_night = sum(x[s][di]["D*"] + x[s][di]["*"] + x[s][di]["N"] for s in med_staff)
        if modes["med_competent_required"] == "hard":
            model.Add(med_day >= 1)
            model.Add(med_night >= 1)
        elif modes["med_competent_required"] == "soft":
            miss_day = model.NewBoolVar(f"miss_med_day_{di}")
            miss_night = model.NewBoolVar(f"miss_med_night_{di}")
            model.Add(med_day == 0).OnlyEnforceIf(miss_day)
            model.Add(med_day >= 1).OnlyEnforceIf(miss_day.Not())
            model.Add(med_night == 0).OnlyEnforceIf(miss_night)
            model.Add(med_night >= 1).OnlyEnforceIf(miss_night.Not())
            soft_terms.append(weights["med_competent_required"] * miss_day)
            soft_terms.append(weights["med_competent_required"] * miss_night)

        # First-aider
        fa_day = sum(x[s][di]["D"] + x[s][di]["D*"] for s in fa_staff)
        fa_night = sum(x[s][di]["D*"] + x[s][di]["*"] + x[s][di]["N"] for s in fa_staff)
        if modes["first_aider_required"] == "hard":
            model.Add(fa_day >= 1)
            model.Add(fa_night >= 1)
        elif modes["first_aider_required"] == "soft":
            miss_day = model.NewBoolVar(f"miss_fa_day_{di}")
            miss_night = model.NewBoolVar(f"miss_fa_night_{di}")
            model.Add(fa_day == 0).OnlyEnforceIf(miss_day)
            model.Add(fa_day >= 1).OnlyEnforceIf(miss_day.Not())
            model.Add(fa_night == 0).OnlyEnforceIf(miss_night)
            model.Add(fa_night >= 1).OnlyEnforceIf(miss_night.Not())
            soft_terms.append(weights["first_aider_required"] * miss_day)
            soft_terms.append(weights["first_aider_required"] * miss_night)

        # No-male-pair-alone
        if modes["no_male_pair_alone"] != "off" and males and females:
            males_day = sum(x[s][di]["D"] + x[s][di]["D*"] for s in males)
            females_day = sum(x[s][di]["D"] + x[s][di]["D*"] for s in females)
            males_night = sum(x[s][di]["D*"] + x[s][di]["*"] + x[s][di]["N"] for s in males)
            females_night = sum(x[s][di]["D*"] + x[s][di]["*"] + x[s][di]["N"] for s in females)

            if modes["no_male_pair_alone"] == "hard":
                any_male_day = model.NewBoolVar(f"any_male_day_{di}")
                model.Add(males_day >= 1).OnlyEnforceIf(any_male_day)
                model.Add(males_day == 0).OnlyEnforceIf(any_male_day.Not())
                model.Add(females_day >= 1).OnlyEnforceIf(any_male_day)

                any_male_night = model.NewBoolVar(f"any_male_night_{di}")
                model.Add(males_night >= 1).OnlyEnforceIf(any_male_night)
                model.Add(males_night == 0).OnlyEnforceIf(any_male_night.Not())
                model.Add(females_night >= 1).OnlyEnforceIf(any_male_night)
            else:  # soft
                viol_day = model.NewBoolVar(f"male_pair_day_{di}")
                model.Add(males_day >= 1).OnlyEnforceIf(viol_day)
                model.Add(females_day == 0).OnlyEnforceIf(viol_day)
                soft_terms.append(weights["no_male_pair_alone"] * viol_day)
                viol_night = model.NewBoolVar(f"male_pair_night_{di}")
                model.Add(males_night >= 1).OnlyEnforceIf(viol_night)
                model.Add(females_night == 0).OnlyEnforceIf(viol_night)
                soft_terms.append(weights["no_male_pair_alone"] * viol_night)

    # Consecutive-day rules (always hard per spec)
    for s in staff_inits:
        for di in range(n_days - 1):
            model.Add(x[s][di]["N"] + x[s][di + 1]["D"] <= 1)
            model.Add(x[s][di]["D*"] + x[s][di + 1]["D*"] <= 1)
            # no_sleepover_before_leave: D*/* today forbids AL/TRN tomorrow.
            # A D* or * shift extends until ~08:00 next day, so the staff is
            # still on duty when their leave/training day officially begins.
            model.Add(
                x[s][di]["D*"] + x[s][di]["*"]
                + x[s][di + 1]["AL"] + x[s][di + 1]["TRN"]
                <= 1
            )

    # Contracted hours — PER WEEK (not rota-aggregate) so each week individually
    # hits the staff's target. This is critical so that when one Flexi is on AL
    # for a specific week, the OTHER flexi gets loaded UP THAT SPECIFIC WEEK
    # (instead of the solver spreading the gap across all weeks and leaving
    # the other flexi under-utilised).
    #
    # Per-week formula (for each staff S, each week W):
    #   actual_hours(S, W) + 12 * AL_days(S, W) + 8 * TRN_days(S, W) + 2
    #       >= target_weekly_hours(S)
    # Non-flexi (mode=hard) cap: actual_hours(S, W) <= target_weekly_hours(S) + 8.
    # Flexi staff get their overtime reward computed PER WEEK too so each week's
    # slack is distributed to whichever flexi has capacity that specific week.
    ot_params = rule_params.get("overtime_prefer_flexi") or {}
    # Determine flexi staff set:
    #   1. If staff_initials_override is non-empty, use that explicit list
    #   2. Else, auto-detect from role == applies_to_role (default "Flexi")
    #   3. Legacy: if `preferred_staff_initials` (single string) is set, use it
    override = ot_params.get("staff_initials_override") or []
    role_match = ot_params.get("applies_to_role", "Flexi")
    legacy_single = ot_params.get("preferred_staff_initials")
    if override:
        ot_flexi_set = set(override)
    elif legacy_single:
        ot_flexi_set = {legacy_single}
    else:
        ot_flexi_set = {s["initials"] for s in staff_list if s.get("role") == role_match}
    ot_weekly_cap = int(ot_params.get("weekly_cap", 48))
    ot_mode = modes.get("overtime_prefer_flexi", "soft")

    for s in staff_inits:
        info = staff_by[s]
        target_weekly = int(info.get("target_weekly_hours", 0))
        if target_weekly <= 0:
            continue  # skip admin-only / zero-hour staff
        is_flexi = (ot_mode != "off") and (s in ot_flexi_set)
        accepts_ot = bool(info.get("accepts_overtime", False))
        # Per-staff overtime acceptance: if the staff has explicitly opted out
        # of overtime (accepts_overtime=false), we apply a STRONG soft penalty
        # for any hour above target — overrides flexi-role auto-detection so
        # T.D. (Flexi but accepts_overtime=false) does NOT absorb slack.
        rewards_overtime = is_flexi and accepts_ot
        non_flexi_mode = modes.get("non_flexi_overage", "hard")
        cap_overage_weekly = max(0, ot_weekly_cap - target_weekly)

        for w in range(weeks):
            di_start = w * 7
            di_end = (w + 1) * 7
            week_idx = range(di_start, di_end)
            al_w = sum(x[s][di]["AL"] for di in week_idx)
            trn_w = sum(x[s][di]["TRN"] for di in week_idx)
            actual_w = sum(
                shift_hours[t] * x[s][di][t] for di in week_idx for t in SHIFT_TYPES
            )

            if modes["contracted_hours_min"] == "hard":
                model.Add(actual_w + 12 * al_w + 8 * trn_w + 2 >= target_weekly)
            elif modes["contracted_hours_min"] == "soft":
                short_w = model.NewIntVar(0, 200, f"hours_short_{s}_w{w}")
                model.Add(actual_w + 12 * al_w + 8 * trn_w + short_w >= target_weekly - 2)
                soft_terms.append(weights["contracted_hours_min"] * short_w)

            over_w = model.NewIntVar(0, 200, f"hours_over_{s}_w{w}")
            model.Add(actual_w - target_weekly <= over_w)

            if rewards_overtime:
                # Diminishing-returns reward curve so flexi don't pin at the
                # weekly cap (e.g. D.A. at 42h every week). Three brackets:
                #  bracket 1 (+0..+4h):   reward weight × 1.0   (encourage)
                #  bracket 2 (+4..+8h):   reward weight × 0.4   (taper)
                #  beyond +8h:            mild penalty           (discourage)
                # Plus a hard cap at the weekly_cap (UK WTR 48h default).
                b1_max = min(4, cap_overage_weekly)
                b2_max = min(4, max(0, cap_overage_weekly - 4))
                b1 = model.NewIntVar(0, max(b1_max, 1), f"flexi_b1_{s}_w{w}")
                b2 = model.NewIntVar(0, max(b2_max, 1), f"flexi_b2_{s}_w{w}")
                b3 = model.NewIntVar(0, 200, f"flexi_b3_{s}_w{w}")
                model.Add(b1 + b2 + b3 == over_w)
                if b1_max > 0:
                    model.Add(b1 <= b1_max)
                else:
                    model.Add(b1 == 0)
                if b2_max > 0:
                    model.Add(b2 <= b2_max)
                else:
                    model.Add(b2 == 0)
                # Strong reward for first 4 hours over target
                if b1_max > 0:
                    soft_terms.append(-weights["overtime_prefer_flexi"] * b1)
                # Weak reward for next 4 hours (40% of base)
                if b2_max > 0:
                    soft_terms.append(-int(weights["overtime_prefer_flexi"] * 0.4) * b2)
                # Beyond +8h: STRONG penalty (200/h) — exceeds opt-out
                # alternative cost (150/h) so the solver pushes slack onto
                # opt-out staff before letting D.A. blow past +8h.
                soft_terms.append((weights["non_flexi_overage"] * 4) * b3)
                # Hard ceiling at the weekly cap (e.g. 48h)
                if cap_overage_weekly > 0:
                    model.Add(over_w <= cap_overage_weekly)
            elif not accepts_ot:
                # Staff explicitly opted out of overtime — hard cap at +12h
                # above target keeps the rota feasible under multi-day
                # Flexi AL scenarios while preventing the worst-case
                # "opt-out staff accidentally carrying 62h alone" pin.
                # The strong soft penalty (150/h) discourages any
                # overage. Note: tighter caps (e.g. +8) were tried but
                # caused INFEASIBLE under multi-day Flexi AL.
                model.Add(over_w <= 12)
                soft_terms.append(weights["non_flexi_overage"] * over_w)
                soft_terms.append(100 * over_w)
            else:
                # Non-flexi — per-week overage
                if non_flexi_mode == "hard":
                    # Per-week cap: actual_w <= target_weekly + 8 (2h/week tolerance).
                    model.Add(actual_w <= target_weekly + 8)
                    soft_terms.append(weights["hours_overage"] * over_w)
                elif non_flexi_mode == "soft":
                    soft_terms.append(weights["non_flexi_overage"] * over_w)
                else:
                    soft_terms.append(weights["hours_overage"] * over_w)

    # D* preference for sleepover-capable staff
    if modes["sleepover_preference"] != "off":
        for s in staff_inits:
            if not staff_by[s].get("can_do_sleepover"):
                continue
            for di in range(n_days):
                # Penalty for D when staff is sleepover-capable
                if modes["sleepover_preference"] == "hard":
                    # "hard" means: never assign D if D* is allowed?
                    # That would be too restrictive — interpret hard
                    # as a 100x weight instead.
                    soft_terms.append(weights["sleepover_preference"] * 100 * x[s][di]["D"])
                else:
                    soft_terms.append(weights["sleepover_preference"] * x[s][di]["D"])

    # Preferred off days
    if modes["preferred_off_days"] != "off":
        for s in staff_inits:
            prefs = {p.lower()[:3] for p in (staff_by[s].get("preferred_off_days") or [])}
            if not prefs:
                continue
            for di, dt in enumerate(days):
                if DOW_NAMES[dt.weekday()].lower() in prefs:
                    work = sum(x[s][di][t] for t in WORKING_SHIFTS)
                    if modes["preferred_off_days"] == "hard":
                        model.Add(work == 0)
                    else:
                        soft_terms.append(weights["preferred_off_days"] * work)

    # Avoid pairs
    if modes["avoid_pairs"] != "off":
        for pair in avoid_pairs:
            a, b = pair.get("a"), pair.get("b")
            if a not in staff_by or b not in staff_by:
                continue
            for di in range(n_days):
                a_day = x[a][di]["D"] + x[a][di]["D*"]
                b_day = x[b][di]["D"] + x[b][di]["D*"]
                both_day = model.NewBoolVar(f"pair_day_{a}_{b}_{di}")
                model.Add(a_day + b_day >= 2).OnlyEnforceIf(both_day)
                model.Add(a_day + b_day <= 1).OnlyEnforceIf(both_day.Not())
                if modes["avoid_pairs"] == "hard":
                    model.Add(both_day == 0)
                else:
                    soft_terms.append(weights["avoid_pairs"] * both_day)

                a_night = x[a][di]["D*"] + x[a][di]["*"] + x[a][di]["N"]
                b_night = x[b][di]["D*"] + x[b][di]["*"] + x[b][di]["N"]
                both_night = model.NewBoolVar(f"pair_night_{a}_{b}_{di}")
                model.Add(a_night + b_night >= 2).OnlyEnforceIf(both_night)
                model.Add(a_night + b_night <= 1).OnlyEnforceIf(both_night.Not())
                if modes["avoid_pairs"] == "hard":
                    model.Add(both_night == 0)
                else:
                    soft_terms.append(weights["avoid_pairs"] * both_night)

    # Weekend fairness
    if modes["weekend_fairness"] != "off":
        weekend_idx = [di for di, dt in enumerate(days) if dt.weekday() >= 5]
        if weekend_idx:
            for s in staff_inits:
                info = staff_by[s]
                shifts_per_week = info.get("target_weekly_hours", 36) / 12.0
                target_ww = round(shifts_per_week * len(weekend_idx) / 7)
                target_ww = max(0, min(target_ww, len(weekend_idx)))
                ww = sum(x[s][di][t] for di in weekend_idx for t in WORKING_SHIFTS)
                over = model.NewIntVar(0, len(weekend_idx), f"we_over_{s}")
                under = model.NewIntVar(0, len(weekend_idx), f"we_under_{s}")
                model.Add(ww - target_ww == over - under)
                soft_terms.append(weights["weekend_fairness"] * over)
                soft_terms.append(weights["weekend_fairness"] * under)

    # Accepted non-OFF requests as soft preferences (Phase 3)
    # Each preference adds a small penalty when the staff's actual shift
    # on that date doesn't match the requested preference.
    accepted_requests = payload.get("accepted_requests") or []
    REQ_WEIGHT = 15
    for req in accepted_requests:
        s = req.get("staff_initials")
        d_str = req.get("date")
        pref = (req.get("shift_preference") or "").upper()
        if s not in staff_by:
            continue
        try:
            di = days.index(_parse_date(d_str))
        except (ValueError, KeyError):
            continue
        wanted = set()
        if pref == "WANT_N":
            wanted = {"N"}
        elif pref == "WANT_D":
            wanted = {"D", "D*"}
        elif pref == "WANT_DSTAR":
            wanted = {"D*"}
        elif pref == "AVOID":
            # AVOID = penalty if working at all
            for t in WORKING_SHIFTS:
                soft_terms.append(REQ_WEIGHT * x[s][di][t])
            continue
        else:
            continue
        # penalty for any not-wanted shift type
        for t in SHIFT_TYPES:
            if t not in wanted:
                soft_terms.append(REQ_WEIGHT * x[s][di][t])

    # Prefer D* over * on night cover — soft penalty per day where * is used
    if modes.get("prefer_dstar_over_star", "soft") != "off":
        for di in range(n_days):
            star_count = sum(x[s][di]["*"] for s in staff_inits)
            # star_count is 0 or 1 due to night cover constraint
            soft_terms.append(weights["prefer_dstar_over_star"] * star_count)

    # -----------------------------------------------------------------
    # senior_weekend_cover: L.M. or L.D. on every Sat & Sun (D or D*).
    # Rotation (preferred senior per week) is a SOFT nudge on top.
    # -----------------------------------------------------------------
    senior_mode = modes.get("senior_weekend_cover", "hard")
    # De-hardcoded: derive senior list from staff `is_senior` flag —
    # empty tuple means rule simply doesn't apply.
    seniors_active = _derive_role_staff(payload["staff"], "is_senior")
    present_seniors = [s for s in seniors_active if s in staff_by]
    if senior_mode != "off" and present_seniors:
        for di, dt in enumerate(days):
            if dt.weekday() >= 5:  # Sat=5, Sun=6
                # AL exemption: if BOTH seniors are forced unavailable that
                # day there is no valid solution to the rule — skip entirely.
                avail_seniors = [sr for sr in present_seniors if not _is_forced_unavail(sr, di)]
                if not avail_seniors:
                    continue
                cover_sum = sum(
                    x[sr][di]["D"] + x[sr][di]["D*"] for sr in avail_seniors
                )
                if senior_mode == "hard":
                    model.Add(cover_sum >= 1)
                else:  # soft
                    miss = model.NewBoolVar(f"senior_weekend_miss_{di}")
                    model.Add(cover_sum == 0).OnlyEnforceIf(miss)
                    model.Add(cover_sum >= 1).OnlyEnforceIf(miss.Not())
                    soft_terms.append(weights["senior_weekend_cover"] * miss)

    # Rotation NUDGE — the manager pre-picks which senior covers each week's
    # weekend. Reward D/D* for the assigned senior on their Sat+Sun; if they're
    # on AL/TRN the hard rule above forces the OTHER senior to step in
    # (reward just doesn't activate).
    rotation = payload.get("senior_weekend_rotation") or []
    if rotation and present_seniors:
        rot_map: dict[int, str] = {}
        for r in rotation:
            wi = r.get("week_index")
            init = r.get("staff_initials")
            if isinstance(wi, int) and init in staff_by:
                rot_map[wi] = init
        for w in range(weeks):
            assigned = rot_map.get(w + 1)
            if not assigned:
                continue
            for di in range(w * 7, min((w + 1) * 7, n_days)):
                if days[di].weekday() >= 5:
                    soft_terms.append(
                        -weights["senior_weekend_rotation_nudge"]
                        * (x[assigned][di]["D"] + x[assigned][di]["D*"])
                    )

    # -----------------------------------------------------------------
    # avoid_pair_seniors (legacy) + avoid_staff_pairs (new).
    # Both rules penalise listed staff pairs from sharing day cover
    # (D or D*) on the same date. avoid_staff_pairs is the modern
    # multi-pair configurable version; avoid_pair_seniors is kept for
    # back-compat when no pairs are configured — it auto-pairs the
    # first two flagged seniors.
    # -----------------------------------------------------------------
    asp_mode = modes.get("avoid_staff_pairs", "soft")
    asp_params = rule_params.get("avoid_staff_pairs") or {}
    asp_pairs_cfg = asp_params.get("pairs") or []
    asp_pairs: list[tuple[str, str, int]] = []
    for p in asp_pairs_cfg:
        a = p.get("staff_a_initials") or p.get("a")
        b = p.get("staff_b_initials") or p.get("b")
        w = int(p.get("weight") or weights["avoid_staff_pairs"])
        if a and b and a != b and a in staff_by and b in staff_by:
            asp_pairs.append((a, b, w))

    if asp_mode != "off" and asp_pairs:
        for a, b, w in asp_pairs:
            for di in range(n_days):
                a_day = x[a][di]["D"] + x[a][di]["D*"]
                b_day = x[b][di]["D"] + x[b][di]["D*"]
                both = model.NewBoolVar(f"asp_{a}_{b}_{di}")
                model.Add(a_day + b_day >= 2).OnlyEnforceIf(both)
                model.Add(a_day + b_day <= 1).OnlyEnforceIf(both.Not())
                if asp_mode == "hard":
                    model.Add(both == 0)
                else:
                    soft_terms.append(w * both)

    # Legacy avoid_pair_seniors — only activates if avoid_staff_pairs is
    # off / empty so the two rules don't double-count. Operates on the
    # first two flagged seniors (the deputy + senior care support pair).
    aps_mode = modes.get("avoid_pair_seniors", "off")
    if aps_mode != "off" and not asp_pairs and len(present_seniors) >= 2:
        a, b = present_seniors[0], present_seniors[1]
        for di in range(n_days):
            a_day = x[a][di]["D"] + x[a][di]["D*"]
            b_day = x[b][di]["D"] + x[b][di]["D*"]
            both = model.NewBoolVar(f"aps_{di}")
            model.Add(a_day + b_day >= 2).OnlyEnforceIf(both)
            model.Add(a_day + b_day <= 1).OnlyEnforceIf(both.Not())
            if aps_mode == "hard":
                model.Add(both == 0)
            else:  # soft
                soft_terms.append(weights["avoid_pair_seniors"] * both)

    # -----------------------------------------------------------------
    # min_sleepover_per_week_for_seniors: per-staff floor on D* count.
    # New params shape: {rules: [{staff_initials: [...], min_per_week: N}, ...]}
    # Penalty is PROPORTIONAL (per missing D*) so the solver is pushed
    # past min=1 toward min=2 when configured. Skips weeks where the
    # staff has ≥5 AL/TRN days (unavailable).
    # -----------------------------------------------------------------
    msl_mode = modes.get("min_sleepover_per_week_for_seniors", "soft")
    if msl_mode != "off":
        msl_params = rule_params.get("min_sleepover_per_week_for_seniors") or {}
        # Backwards-compat: old shape {staff_initials, min_sleepovers_per_week}.
        if "rules" in msl_params:
            msl_rules = msl_params.get("rules") or []
        else:
            # Legacy shape — fall back to role-derived seniors so the
            # rule keeps working on unmigrated configs.
            legacy_inits = msl_params.get("staff_initials") or list(_derive_role_staff(staff_list, "is_senior"))
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
                    week_idx = range(w * 7, (w + 1) * 7)
                    dstar_w = sum(x[s][di]["D*"] for di in week_idx)
                    # AL-aware scaling. We use FORCED unavail (AL/TRN locks)
                    # rather than CP-SAT `AL`/`TRN` variables because forced
                    # cells are deterministic at model-build time — using
                    # variable AL counts would let the solver pretend a staff
                    # is on AL to dodge the rule (it can't, because AL is
                    # constrained to forced-only, but using forced counts is
                    # cleaner and matches the validator).
                    forced_unavail = _unavail_count_in_week(s, w)
                    # Skip entirely when staff has >=3 AL/TRN days that week
                    # (matches user spec: "AL is a clean break").
                    if forced_unavail >= 3:
                        continue
                    # Scale: each pair of unavailable days knocks 1 off the
                    # required min (rough heuristic per user spec).
                    eff_min = max(0, min_n - (forced_unavail // 2))
                    if eff_min <= 0:
                        continue
                    if msl_mode == "hard":
                        model.Add(dstar_w >= eff_min)
                    else:
                        # Soft: proportional penalty per missing D*.
                        short_raw = model.NewIntVar(0, eff_min, f"msl_short_{s}_w{w}_{eff_min}")
                        model.Add(short_raw + dstar_w >= eff_min)
                        soft_terms.append(weights["min_sleepover_per_week_for_seniors"] * short_raw)

    # -----------------------------------------------------------------
    # senior_monday_cover: each Monday should have at least one of the
    # configured senior staff on a working shift (D or D*). Soft default.
    # -----------------------------------------------------------------
    smc_mode = modes.get("senior_monday_cover", "soft")
    if smc_mode != "off":
        smc_params = rule_params.get("senior_monday_cover") or {}
        # Role-derived fallback — list of seniors flagged `is_senior`.
        smc_default = list(_derive_role_staff(staff_list, "is_senior"))
        smc_staff = [s for s in (smc_params.get("staff_initials") or smc_default)
                     if s in staff_by]
        if smc_staff:
            for di, dt in enumerate(days):
                if dt.weekday() == 0:  # Monday
                    # AL exemption: skip entirely when all configured senior
                    # staff are forced unavailable that Monday.
                    avail_smc = [s for s in smc_staff if not _is_forced_unavail(s, di)]
                    if not avail_smc:
                        continue
                    cover_sum = sum(
                        x[s][di]["D"] + x[s][di]["D*"] for s in avail_smc
                    )
                    if smc_mode == "hard":
                        model.Add(cover_sum >= 1)
                    else:  # soft
                        miss = model.NewBoolVar(f"smc_miss_{di}")
                        model.Add(cover_sum == 0).OnlyEnforceIf(miss)
                        model.Add(cover_sum >= 1).OnlyEnforceIf(miss.Not())
                        soft_terms.append(weights["senior_monday_cover"] * miss)

    # -----------------------------------------------------------------
    # respect_shift_preference: per-staff nudge toward preferred shift type.
    # Only applies to staff who can do BOTH days AND nights (else preference
    # is irrelevant). "day" preference penalises N and *; "night" preference
    # penalises D and D*. "no_preference" → no penalty.
    # -----------------------------------------------------------------
    rsp_mode = modes.get("respect_shift_preference", "soft")
    if rsp_mode != "off":
        for s in staff_inits:
            info = staff_by[s]
            if not (info.get("can_do_days") and info.get("can_do_nights")):
                continue  # not dual-capable → preference is moot
            pref = (info.get("shift_preference") or "no_preference").lower()
            if pref not in {"day", "night"}:
                continue
            penalised = {"N", "*"} if pref == "day" else {"D", "D*"}
            for di in range(n_days):
                for shift in penalised:
                    if rsp_mode == "hard":
                        # Hard mode forbids the off-preference shift entirely
                        # (rare — usually soft).
                        model.Add(x[s][di][shift] == 0)
                    else:
                        soft_terms.append(weights["respect_shift_preference"] * x[s][di][shift])

    # -----------------------------------------------------------------
    # avoid_star_then_night & avoid_star_then_day: penalise consecutive
    # *→N and *→D patterns. *→D has per-staff override weights (e.g.
    # L.D. has weight 60 vs general 20).
    # -----------------------------------------------------------------
    asn_mode = modes.get("avoid_star_then_night", "soft")
    asd_mode = modes.get("avoid_star_then_day", "soft")
    if asn_mode != "off" or asd_mode != "off":
        asd_params = rule_params.get("avoid_star_then_day") or {}
        asd_general = int(asd_params.get("general_weight", weights["avoid_star_then_day"]))
        # Role-derived fallback: seniors get the stronger per-staff weight
        # (they dislike *→D more strongly than general staff).
        senior_overrides = {s: 60 for s in _derive_role_staff(staff_list, "is_senior")}
        asd_overrides = asd_params.get("staff_overrides") or senior_overrides
        for s in staff_inits:
            for di in range(n_days - 1):
                # *→N
                if asn_mode != "off":
                    pair_n = model.NewBoolVar(f"asn_{s}_{di}")
                    model.AddBoolAnd([x[s][di]["*"], x[s][di + 1]["N"]]).OnlyEnforceIf(pair_n)
                    model.AddBoolOr([x[s][di]["*"].Not(), x[s][di + 1]["N"].Not()]).OnlyEnforceIf(pair_n.Not())
                    if asn_mode == "hard":
                        model.Add(pair_n == 0)
                    else:
                        soft_terms.append(weights["avoid_star_then_night"] * pair_n)
                # *→D
                if asd_mode != "off":
                    pair_d = model.NewBoolVar(f"asd_{s}_{di}")
                    model.AddBoolAnd([x[s][di]["*"], x[s][di + 1]["D"]]).OnlyEnforceIf(pair_d)
                    model.AddBoolOr([x[s][di]["*"].Not(), x[s][di + 1]["D"].Not()]).OnlyEnforceIf(pair_d.Not())
                    if asd_mode == "hard":
                        model.Add(pair_d == 0)
                    else:
                        w_for_s = int(asd_overrides.get(s, asd_general))
                        soft_terms.append(w_for_s * pair_d)

    # -----------------------------------------------------------------
    # avoid_star_for_staff: listed staff dislike bare `*` (sleepover-only).
    # Soft penalty per `*` shift assigned to them.
    # -----------------------------------------------------------------
    asfs_mode = modes.get("avoid_star_for_staff", "soft")
    asfs_staff: list[str] = []
    if asfs_mode != "off":
        asfs_params = rule_params.get("avoid_star_for_staff") or {}
        # Role-derived fallback: seniors dislike bare `*` by default.
        asfs_default = list(_derive_role_staff(staff_list, "is_senior"))
        asfs_staff = [s for s in (asfs_params.get("staff_initials") or asfs_default)
                      if s in staff_by]
        for s in asfs_staff:
            for di in range(n_days):
                if asfs_mode == "hard":
                    model.Add(x[s][di]["*"] == 0)
                else:
                    soft_terms.append(weights["avoid_star_for_staff"] * x[s][di]["*"])

    # -----------------------------------------------------------------
    # max_sleepover_per_week: per-staff cap on D* count per week.
    # params.rules = [{staff_initials: [...], max_per_week: int}, ...]
    # -----------------------------------------------------------------
    msx_mode = modes.get("max_sleepover_per_week", "soft")
    if msx_mode != "off":
        msx_params = rule_params.get("max_sleepover_per_week") or {}
        msx_rules = msx_params.get("rules") or []
        for rule_entry in msx_rules:
            cap = rule_entry.get("max_per_week")
            if cap is None:
                continue
            cap = int(cap)
            entry_staff = [s for s in (rule_entry.get("staff_initials") or [])
                           if s in staff_by]
            for s in entry_staff:
                for w in range(weeks):
                    week_idx = range(w * 7, (w + 1) * 7)
                    dstar_w = sum(x[s][di]["D*"] for di in week_idx)
                    if msx_mode == "hard":
                        model.Add(dstar_w <= cap)
                    else:
                        # over_w_dstar = max(0, dstar_w - cap)
                        over_dstar = model.NewIntVar(0, 7, f"msx_{s}_w{w}")
                        model.Add(dstar_w - cap <= over_dstar)
                        model.Add(over_dstar >= 0)
                        soft_terms.append(weights["max_sleepover_per_week"] * over_dstar)

    # -----------------------------------------------------------------
    # fair_star_distribution: spread `*` across eligible staff. Eligible
    # = can_do_sleepover=true AND NOT in avoid_star_for_staff list.
    # Penalises (max − min) of star count across eligibles.
    # -----------------------------------------------------------------
    fsd_mode = modes.get("fair_star_distribution", "soft")
    if fsd_mode != "off":
        avoid_set = set(asfs_staff)  # set in solver above
        eligible = [
            s for s in staff_inits
            if staff_by[s].get("can_do_sleepover") and s not in avoid_set
        ]
        if len(eligible) >= 2:
            star_counts = []
            for s in eligible:
                cnt = model.NewIntVar(0, n_days, f"star_count_{s}")
                model.Add(cnt == sum(x[s][di]["*"] for di in range(n_days)))
                star_counts.append(cnt)
            star_max = model.NewIntVar(0, n_days, "star_max")
            star_min = model.NewIntVar(0, n_days, "star_min")
            model.AddMaxEquality(star_max, star_counts)
            model.AddMinEquality(star_min, star_counts)
            spread = model.NewIntVar(0, n_days, "star_spread")
            model.Add(spread == star_max - star_min)
            soft_terms.append(weights["fair_star_distribution"] * spread)

    # -----------------------------------------------------------------
    # weekday_weekend_split: per-staff target count of shift_types on
    # weekdays (Mon-Fri) AND weekend days (Sat-Sun) per week. Penalty
    # per unit of |actual − target|. Useful for J.R. who prefers exactly
    # 1 weekday N + 1 weekend N every week.
    # -----------------------------------------------------------------
    wws_mode = modes.get("weekday_weekend_split", "soft")
    if wws_mode != "off":
        wws_params = rule_params.get("weekday_weekend_split") or {}
        for rule_entry in (wws_params.get("rules") or []):
            wd_target = int(rule_entry.get("weekday_target", 1))
            we_target = int(rule_entry.get("weekend_target", 1))
            shift_types = list(rule_entry.get("shift_types") or ["N"])
            entry_inits = rule_entry.get("staff_initials")
            # Allow either a string or a list
            if isinstance(entry_inits, str):
                entry_staff = [entry_inits] if entry_inits in staff_by else []
            else:
                entry_staff = [s for s in (entry_inits or []) if s in staff_by]
            for s in entry_staff:
                for w in range(weeks):
                    weekday_var_expr = []
                    weekend_var_expr = []
                    weekday_avail_days = 0
                    weekend_avail_days = 0
                    for di in range(w * 7, (w + 1) * 7):
                        is_weekend = days[di].weekday() >= 5
                        # AL exemption: skip days where staff is forced
                        # unavailable. This makes the sub-window's effective
                        # day-count smaller and we'll skip the whole sub-
                        # window if zero days remain.
                        if _is_forced_unavail(s, di):
                            continue
                        if is_weekend:
                            weekend_avail_days += 1
                        else:
                            weekday_avail_days += 1
                        for shift in shift_types:
                            if is_weekend:
                                weekend_var_expr.append(x[s][di][shift])
                            else:
                                weekday_var_expr.append(x[s][di][shift])
                    weekday_var = sum(weekday_var_expr) if weekday_var_expr else 0
                    weekend_var = sum(weekend_var_expr) if weekend_var_expr else 0
                    # |weekday_var - wd_target| — skipped when no available weekday
                    if weekday_avail_days > 0 and weekday_var_expr:
                        wd_diff = model.NewIntVar(0, 10, f"wws_wd_{s}_w{w}")
                        model.Add(wd_diff >= weekday_var - wd_target)
                        model.Add(wd_diff >= wd_target - weekday_var)
                        if wws_mode == "hard":
                            model.Add(wd_diff == 0)
                        else:
                            soft_terms.append(weights["weekday_weekend_split"] * wd_diff)
                    if weekend_avail_days > 0 and weekend_var_expr:
                        we_diff = model.NewIntVar(0, 10, f"wws_we_{s}_w{w}")
                        model.Add(we_diff >= weekend_var - we_target)
                        model.Add(we_diff >= we_target - weekend_var)
                        if wws_mode == "hard":
                            model.Add(we_diff == 0)
                        else:
                            soft_terms.append(weights["weekday_weekend_split"] * we_diff)

    # -----------------------------------------------------------------
    # pair_companion_on_day: if a focal staff is working a day shift on
    # a configured weekday (e.g. C.E. on Wed), at least one of the listed
    # companions must also be working a day shift that same day.
    # AL exemption: skip when focal is forced AL/TRN that day, or when
    # all companions are forced AL/TRN that day.
    # -----------------------------------------------------------------
    pco_mode = modes.get("pair_companion_on_day", "soft")
    if pco_mode != "off":
        pco_params = rule_params.get("pair_companion_on_day") or {}
        pco_rules = pco_params.get("rules") or []
        for ridx, rule_entry in enumerate(pco_rules):
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
            shift_types_in = rule_entry.get("shift_types") or ["D", "D*"]
            shift_types_set = {sh for sh in shift_types_in if sh in SHIFT_TYPES}
            if not shift_types_set:
                continue
            for di, dt in enumerate(days):
                if dt.weekday() != target_dow:
                    continue
                # AL exemption #1: focal forced unavailable that day.
                if _is_forced_unavail(focal, di):
                    continue
                avail_companions = [c for c in companions if not _is_forced_unavail(c, di)]
                # AL exemption #2: no available companions to satisfy the rule.
                if not avail_companions:
                    continue
                # focal_works = sum of x[focal][di][shift] over shift_types
                focal_works = sum(x[focal][di][sh] for sh in shift_types_set)
                # companion_present = sum of x[c][di][shift] for any c in avail_companions
                comp_present = sum(
                    x[c][di][sh] for c in avail_companions for sh in shift_types_set
                )
                if pco_mode == "hard":
                    # focal_works <= 1 (since each staff has one shift), so:
                    # focal_works (0 or 1) implies comp_present >= 1.
                    model.Add(comp_present >= focal_works)
                else:
                    # Soft: penalty when focal works AND comp_present == 0.
                    miss = model.NewBoolVar(f"pco_{ridx}_{di}")
                    # miss = focal_works AND NOT comp_present
                    model.Add(focal_works >= 1).OnlyEnforceIf(miss)
                    model.Add(comp_present == 0).OnlyEnforceIf(miss)
                    model.Add(focal_works + comp_present >= 1).OnlyEnforceIf(miss.Not())
                    soft_terms.append(weights["pair_companion_on_day"] * miss)

    # -----------------------------------------------------------------
    # weekend_off_per_rota: every staff should have at least ONE weekend
    # (Sat+Sun both OFF/AL/TRN) in the rota. Penalty fires when a staff
    # has ZERO full weekends off across the 4-week window.
    # Staff forced AL/TRN on EVERY weekend day (e.g. whole rota AL) are
    # exempt — they've effectively got the whole rota off.
    # -----------------------------------------------------------------
    wofr_mode = modes.get("weekend_off_per_rota", "soft")
    if wofr_mode != "off":
        # Build weekend-pair indices [(sat_di, sun_di), ...] for each
        # complete Sat/Sun pair in the rota.
        weekend_pairs: list[tuple[int, int]] = []
        for di in range(n_days - 1):
            if days[di].weekday() == 5 and days[di + 1].weekday() == 6:
                weekend_pairs.append((di, di + 1))

        if weekend_pairs:
            # Non-working shifts count toward "off": OFF + AL + TRN.
            OFF_TYPES = ("OFF", "AL", "TRN")
            for s in staff_inits:
                # Exemption: staff forced unavailable on EVERY weekend day
                # (entire-rota AL etc.) skip the rule.
                all_weekends_forced = all(
                    _is_forced_unavail(s, sat_di)
                    and _is_forced_unavail(s, sun_di)
                    for sat_di, sun_di in weekend_pairs
                )
                if all_weekends_forced:
                    continue

                # For each weekend, indicator = both Sat AND Sun are off.
                weekend_off_flags: list[cp_model.IntVar] = []
                for w_idx, (sat_di, sun_di) in enumerate(weekend_pairs):
                    sat_off = sum(x[s][sat_di][t] for t in OFF_TYPES)
                    sun_off = sum(x[s][sun_di][t] for t in OFF_TYPES)
                    w_off = model.NewBoolVar(f"wofr_{s}_{w_idx}_off")
                    # w_off == 1 iff sat_off == 1 AND sun_off == 1.
                    model.Add(sat_off + sun_off >= 2).OnlyEnforceIf(w_off)
                    model.Add(sat_off + sun_off <= 1).OnlyEnforceIf(w_off.Not())
                    weekend_off_flags.append(w_off)

                # any_off = 1 iff SUM(w_off) >= 1
                any_off = model.NewBoolVar(f"wofr_{s}_any")
                total_off = sum(weekend_off_flags)
                model.Add(total_off >= 1).OnlyEnforceIf(any_off)
                model.Add(total_off == 0).OnlyEnforceIf(any_off.Not())

                if wofr_mode == "hard":
                    model.Add(any_off == 1)
                else:
                    # Penalty when the staff has ZERO weekends off.
                    miss = model.NewBoolVar(f"wofr_{s}_miss")
                    model.Add(any_off == 0).OnlyEnforceIf(miss)
                    model.Add(any_off == 1).OnlyEnforceIf(miss.Not())
                    soft_terms.append(weights["weekend_off_per_rota"] * miss)

    if soft_terms:
        model.Minimize(sum(soft_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    elapsed = int((time.time() - started) * 1000)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _build_failure_response(status, payload, elapsed, forced_cells)

    rota = []
    for di, dt in enumerate(days):
        assignments = []
        for s in staff_inits:
            chosen = next(t for t in SHIFT_TYPES if solver.Value(x[s][di][t]) == 1)
            assignments.append({"staff_initials": s, "shift": chosen})
        rota.append({
            "date": dt.isoformat(),
            "day_of_week": DOW_NAMES[dt.weekday()],
            "assignments": assignments,
        })

    warnings = []
    for s in staff_inits:
        info = staff_by[s]
        target_total = info.get("target_weekly_hours", 0) * weeks
        actual_h = 0
        for di in range(n_days):
            for t in SHIFT_TYPES:
                if solver.Value(x[s][di][t]) == 1:
                    actual_h += shift_hours[t]
        if target_total > 0 and abs(actual_h - target_total) > 0:
            warnings.append(
                f"{s} assigned {actual_h}h vs target {target_total}h over {weeks}w"
            )

    return {
        "success": True,
        "rota": rota,
        "warnings": warnings,
        "soft_violations_score": int(solver.ObjectiveValue()) if soft_terms else 0,
        "solve_time_ms": elapsed,
        "solver_status": solver.StatusName(status),
        "rule_modes": modes,
    }


# ---------------------------------------------------------------------------
def _build_failure_response(status, payload, elapsed_ms, forced_cells):
    name_map = {
        cp_model.UNKNOWN: "UNKNOWN",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.INFEASIBLE: "INFEASIBLE",
    }
    status_name = name_map.get(status, str(status))

    start_date = _parse_date(payload["rota_start_date"])
    weeks = int(payload.get("weeks", 4))
    days = _date_range(start_date, weeks)
    staff_list = payload["staff"]
    staff_by = {s["initials"]: s for s in staff_list}

    blocking = []
    for dt in days:
        d_str = dt.isoformat()
        unavailable = set()
        for (init, d), shift in forced_cells.items():
            if d == d_str and shift in {"AL", "TRN", "OFF"}:
                unavailable.add(init)
        avail = [s for s in staff_by.values() if s["initials"] not in unavailable]
        # Manager / admin-only staff treated as unavailable for solver purposes
        avail_for_shifts = [s for s in avail if not (s.get("is_admin_only") or s.get("is_manager"))]
        day_cap = [s for s in avail_for_shifts if s.get("can_do_days")]
        night_cap = [s for s in avail_for_shifts if s.get("can_do_nights") or s.get("can_do_sleepover")]
        med_day = [s for s in day_cap if s.get("medication_competent")]
        # Relaxed: any night-side staff being med-competent counts
        med_night = [s for s in night_cap if s.get("medication_competent")]
        fa_day = [s for s in day_cap if s.get("first_aider")]
        fa_night = [s for s in night_cap if s.get("first_aider")]

        problems = []
        if len(day_cap) < 2:
            problems.append(f"only {len(day_cap)} day-capable staff available (need 2)")
        if len(night_cap) < 2:
            problems.append(f"only {len(night_cap)} night-capable staff available (need 2)")
        if not med_day:
            problems.append("no medication-competent staff available for day shift")
        if not med_night:
            problems.append("no medication-competent staff available for night shift")
        if not fa_day:
            problems.append("no first-aider available for day shift")
        if not fa_night:
            problems.append("no first-aider available for night shift")
        if problems:
            blocking.append({"date": d_str, "day_of_week": DOW_NAMES[dt.weekday()], "problems": problems})

    if blocking:
        first = blocking[0]
        reason = f"{first['day_of_week']} {first['date']}: " + "; ".join(first["problems"])
    else:
        reason = (
            f"Solver returned {status_name}. No single-day blocker found — "
            "likely a multi-day conflict (consecutive-shift, contracted-hours, "
            "or a combination)."
        )

    return {
        "success": False,
        "reason": reason,
        "blocking_constraints": blocking,
        "solver_status": status_name,
        "solve_time_ms": elapsed_ms,
    }
