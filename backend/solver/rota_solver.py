"""
Grizedale Rota Solver — Phase 0
================================

Builds a 4-week rota for a UK care home using Google OR-Tools CP-SAT.

Decision variable: x[staff, day, shift_type] = 1 if staff works that shift on that day.
Shift types: D, D*, N, *, OFF, AL, TRN.

Hard rules encoded:
    - Exactly one shift type per (staff, day)
    - Daily day cover: 2*D OR 1*D + 1*D*  (i.e. count_D + count_Dstar == 2 AND count_Dstar <= 1)
    - Daily night cover: D* + N OR * + N  (i.e. count_N == 1 AND count_Dstar + count_star == 1)
    - At least 1 medication-competent staff per shift (day shift, night shift)
    - At least 1 first-aider per shift
    - When D.A. or A.A. is on a shift, at least 1 female must also be on that shift
      (i.e. males may not be the only two staff on a given shift)
    - Capability flags (can_do_days / can_do_nights / can_do_sleepover) honoured
    - N -> D forbidden across consecutive calendar days
    - D* -> D* forbidden across consecutive calendar days
    - Locked cells preserved exactly
    - Annual leave (AL) and training (TRN) cells preserved exactly

Soft rules (penalties in objective):
    - Manager (J.C.) on weekday in any working shift -> very high penalty
    - Deviation from target_weekly_hours -> penalty per hour
    - Preferred-off-day violations -> penalty
    - Avoid-pair violations on same shift -> penalty
    - Weekend fairness (variance of weekend-off counts) -> penalty
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from ortools.sat.python import cp_model


SHIFT_TYPES = ["D", "D*", "N", "*", "OFF", "AL", "TRN"]
WORKING_SHIFTS = {"D", "D*", "N", "*"}
DAY_COVER_SHIFTS = {"D", "D*"}        # contribute to daytime cover (08-20)
NIGHT_COVER_SHIFTS = {"N", "D*", "*"}  # contribute to nighttime cover (sleepover or waking)
SHIFT_HOURS = {
    "D": 12,
    "D*": 14,   # 12h day + 2h sleepover allowance (counts toward weekly hours)
    "N": 12,
    "*": 0,     # sleepover-only, no working hours
    "OFF": 0,
    "AL": 0,
    "TRN": 0,
}

DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Penalty weights for soft rules
W_MANAGER_WEEKDAY = 10_000
W_HOURS_DEVIATION = 5     # per hour deviation from target_weekly_hours
W_PREFERRED_OFF = 100     # per violation
W_AVOID_PAIR = 200        # per shift where the pair is together
W_WEEKEND_FAIRNESS = 25   # per unit variance proxy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _date_range(start: date, weeks: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(weeks * 7)]


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------
def solve_rota(payload: dict[str, Any], time_limit_s: int = 10) -> dict[str, Any]:
    """Run the CP-SAT solver and return a structured response."""
    started = time.time()

    start_date = _parse_date(payload["rota_start_date"])
    weeks = int(payload.get("weeks", 4))
    days = _date_range(start_date, weeks)
    n_days = len(days)

    staff_list = payload["staff"]
    staff_by_initials = {s["initials"]: s for s in staff_list}
    staff_initials = [s["initials"] for s in staff_list]

    rules = payload.get("rules", {}) or {}
    require_med = rules.get("med_competent_required", True)
    require_fa = rules.get("first_aider_required", True)
    no_male_pair = rules.get("no_male_pair_alone", True)
    manager_weekday_admin = rules.get("manager_weekday_admin", True)

    leave = payload.get("leave", []) or []
    locked_cells = payload.get("locked_cells", []) or []
    avoid_pairs = payload.get("avoid_pairs", []) or []

    # Index leave/locked by (initials, date_str)
    forced_cells: dict[tuple[str, str], str] = {}
    for entry in leave:
        forced_cells[(entry["staff_initials"], entry["date"])] = entry.get("type", "AL")
    for entry in locked_cells:
        forced_cells[(entry["staff_initials"], entry["date"])] = entry["shift"]

    model = cp_model.CpModel()

    # x[s][d_idx][t] = bool var
    x: dict[str, dict[int, dict[str, cp_model.IntVar]]] = {}
    for s in staff_initials:
        x[s] = {}
        for di, dt in enumerate(days):
            x[s][di] = {}
            for t in SHIFT_TYPES:
                x[s][di][t] = model.NewBoolVar(f"x_{s}_{di}_{t}")
            # Exactly one shift type per (staff, day)
            model.Add(sum(x[s][di][t] for t in SHIFT_TYPES) == 1)

    # Capability flags
    for s in staff_initials:
        info = staff_by_initials[s]
        for di in range(n_days):
            if not info.get("can_do_days", False):
                model.Add(x[s][di]["D"] == 0)
            if not info.get("can_do_sleepover", False):
                model.Add(x[s][di]["D*"] == 0)
                model.Add(x[s][di]["*"] == 0)
            else:
                # D* requires both day capability AND sleepover; * requires night/sleepover
                if not info.get("can_do_days", False):
                    model.Add(x[s][di]["D*"] == 0)
            if not info.get("can_do_nights", False):
                model.Add(x[s][di]["N"] == 0)
                # * (sleepover-only) is generally a night responsibility — allow
                # only if can_do_sleepover; we don't gate on can_do_nights for *
                # to keep flexibility.

    # Forced cells (locked / AL / TRN)
    for (init, d_str), shift in forced_cells.items():
        if init not in staff_by_initials:
            continue
        if shift not in SHIFT_TYPES:
            continue
        # Find the day index
        try:
            d_idx = days.index(_parse_date(d_str))
        except ValueError:
            continue
        for t in SHIFT_TYPES:
            model.Add(x[init][d_idx][t] == (1 if t == shift else 0))

    # Daily cover constraints
    for di in range(n_days):
        count_D = sum(x[s][di]["D"] for s in staff_initials)
        count_Dstar = sum(x[s][di]["D*"] for s in staff_initials)
        count_N = sum(x[s][di]["N"] for s in staff_initials)
        count_star = sum(x[s][di]["*"] for s in staff_initials)

        # Day: 2*D OR 1*D + 1*D*  =>  count_D + count_Dstar == 2 AND count_Dstar <= 1
        model.Add(count_D + count_Dstar == 2)
        model.Add(count_Dstar <= 1)
        # Night: D* + N OR * + N  =>  count_N == 1 AND count_Dstar + count_star == 1
        model.Add(count_N == 1)
        model.Add(count_Dstar + count_star == 1)

        # Per-shift coverage: med-competent + first-aider
        med_staff = [s for s in staff_initials if staff_by_initials[s].get("medication_competent")]
        fa_staff = [s for s in staff_initials if staff_by_initials[s].get("first_aider")]

        if require_med:
            # Day shift must include >=1 med-competent
            model.Add(sum(x[s][di]["D"] + x[s][di]["D*"] for s in med_staff) >= 1)
            # Night shift must include >=1 med-competent (D*, *, or N)
            model.Add(sum(x[s][di]["D*"] + x[s][di]["*"] + x[s][di]["N"] for s in med_staff) >= 1)

        if require_fa:
            model.Add(sum(x[s][di]["D"] + x[s][di]["D*"] for s in fa_staff) >= 1)
            model.Add(sum(x[s][di]["D*"] + x[s][di]["*"] + x[s][di]["N"] for s in fa_staff) >= 1)

        # No-male-pair-alone: when any male is on a shift, at least 1 female
        # must also be on the same shift.
        if no_male_pair:
            males = [s for s in staff_initials if staff_by_initials[s].get("gender") == "M"]
            females = [s for s in staff_initials if staff_by_initials[s].get("gender") == "F"]

            # Day shift
            if males and females:
                # If any male on day -> females_on_day >= 1
                # Sum over males of day-presence is in [0, 2].
                males_on_day = sum(x[s][di]["D"] + x[s][di]["D*"] for s in males)
                females_on_day = sum(x[s][di]["D"] + x[s][di]["D*"] for s in females)
                # If males_on_day >= 1 then females_on_day >= 1
                # Equivalent: females_on_day >= 1 OR males_on_day == 0
                # Encode using big-M with bool
                any_male_day = model.NewBoolVar(f"any_male_day_{di}")
                model.Add(males_on_day >= 1).OnlyEnforceIf(any_male_day)
                model.Add(males_on_day == 0).OnlyEnforceIf(any_male_day.Not())
                model.Add(females_on_day >= 1).OnlyEnforceIf(any_male_day)

                # Night shift
                males_on_night = sum(x[s][di]["D*"] + x[s][di]["*"] + x[s][di]["N"] for s in males)
                females_on_night = sum(x[s][di]["D*"] + x[s][di]["*"] + x[s][di]["N"] for s in females)
                any_male_night = model.NewBoolVar(f"any_male_night_{di}")
                model.Add(males_on_night >= 1).OnlyEnforceIf(any_male_night)
                model.Add(males_on_night == 0).OnlyEnforceIf(any_male_night.Not())
                model.Add(females_on_night >= 1).OnlyEnforceIf(any_male_night)

    # Consecutive-day constraints
    for s in staff_initials:
        for di in range(n_days - 1):
            # N -> D forbidden
            model.Add(x[s][di]["N"] + x[s][di + 1]["D"] <= 1)
            # D* -> D* forbidden
            model.Add(x[s][di]["D*"] + x[s][di + 1]["D*"] <= 1)

    # ----------------------------------------------------------------------
    # Objective: minimise weighted soft-rule violations
    # ----------------------------------------------------------------------
    penalty_terms: list[cp_model.IntVar | int] = []

    # 1. Manager weekday admin (very high penalty if J.C. has any working shift on Mon–Fri)
    if manager_weekday_admin:
        for s in staff_initials:
            info = staff_by_initials[s]
            if not info.get("manager_weekday_admin"):
                continue
            for di, dt in enumerate(days):
                if dt.weekday() < 5:  # Mon-Fri
                    working = sum(x[s][di][t] for t in WORKING_SHIFTS)
                    penalty_terms.append(W_MANAGER_WEEKDAY * working)

    # 2. Hours target deviation
    for s in staff_initials:
        info = staff_by_initials[s]
        target_total = info.get("target_weekly_hours", 0) * weeks
        actual = sum(SHIFT_HOURS[t] * x[s][di][t] for di in range(n_days) for t in SHIFT_TYPES)
        # |actual - target| via two slack vars
        over = model.NewIntVar(0, 1000, f"hours_over_{s}")
        under = model.NewIntVar(0, 1000, f"hours_under_{s}")
        model.Add(actual - target_total == over - under)
        penalty_terms.append(W_HOURS_DEVIATION * over)
        penalty_terms.append(W_HOURS_DEVIATION * under)

    # 3. Preferred off days
    for s in staff_initials:
        info = staff_by_initials[s]
        prefs = info.get("preferred_off_days", []) or []
        if not prefs:
            continue
        pref_set = set(p.lower()[:3] for p in prefs)  # e.g. "Sat", "sun"
        for di, dt in enumerate(days):
            dow = DOW_NAMES[dt.weekday()].lower()
            if dow in pref_set:
                working = sum(x[s][di][t] for t in WORKING_SHIFTS)
                penalty_terms.append(W_PREFERRED_OFF * working)

    # 4. Avoid pairs
    for pair in avoid_pairs:
        a = pair.get("a")
        b = pair.get("b")
        if a not in staff_by_initials or b not in staff_by_initials:
            continue
        for di in range(n_days):
            # Together on day shift
            a_day = x[a][di]["D"] + x[a][di]["D*"]
            b_day = x[b][di]["D"] + x[b][di]["D*"]
            both_day = model.NewBoolVar(f"pair_day_{a}_{b}_{di}")
            model.Add(a_day + b_day >= 2).OnlyEnforceIf(both_day)
            model.Add(a_day + b_day <= 1).OnlyEnforceIf(both_day.Not())
            penalty_terms.append(W_AVOID_PAIR * both_day)
            # Together on night shift
            a_night = x[a][di]["D*"] + x[a][di]["*"] + x[a][di]["N"]
            b_night = x[b][di]["D*"] + x[b][di]["*"] + x[b][di]["N"]
            both_night = model.NewBoolVar(f"pair_night_{a}_{b}_{di}")
            model.Add(a_night + b_night >= 2).OnlyEnforceIf(both_night)
            model.Add(a_night + b_night <= 1).OnlyEnforceIf(both_night.Not())
            penalty_terms.append(W_AVOID_PAIR * both_night)

    # 5. Weekend fairness — equalise count of weekends each staff has fully off.
    # Approximate by penalising deviation of "weekend working days" from the mean.
    weekend_indices = [di for di, dt in enumerate(days) if dt.weekday() >= 5]
    if weekend_indices and len(staff_initials) > 0:
        weekend_work_per_staff = {}
        for s in staff_initials:
            ww = sum(x[s][di][t] for di in weekend_indices for t in WORKING_SHIFTS)
            weekend_work_per_staff[s] = ww
        # Mean (integer): total weekend slots required ~= 4 staff * 8 weekend days = 32
        # We'll use pairwise absolute differences with a representative
        # baseline: for each staff, deviation from average expressed as
        # |ww - target_ww| where target_ww = round(target_weekly_hours / 12 * (weekend_days / 7))
        for s in staff_initials:
            info = staff_by_initials[s]
            shifts_per_week = info.get("target_weekly_hours", 36) / 12.0
            target_ww = round(shifts_per_week * len(weekend_indices) / 7)
            target_ww = max(0, min(target_ww, len(weekend_indices)))
            over = model.NewIntVar(0, len(weekend_indices), f"we_over_{s}")
            under = model.NewIntVar(0, len(weekend_indices), f"we_under_{s}")
            model.Add(weekend_work_per_staff[s] - target_ww == over - under)
            penalty_terms.append(W_WEEKEND_FAIRNESS * over)
            penalty_terms.append(W_WEEKEND_FAIRNESS * under)

    if penalty_terms:
        model.Minimize(sum(penalty_terms))

    # ----------------------------------------------------------------------
    # Solve
    # ----------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)
    elapsed_ms = int((time.time() - started) * 1000)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _build_failure_response(
            status=status,
            payload=payload,
            elapsed_ms=elapsed_ms,
            forced_cells=forced_cells,
        )

    # Extract solution
    rota: list[dict[str, Any]] = []
    for di, dt in enumerate(days):
        assignments = []
        for s in staff_initials:
            chosen = None
            for t in SHIFT_TYPES:
                if solver.Value(x[s][di][t]) == 1:
                    chosen = t
                    break
            assignments.append({"staff_initials": s, "shift": chosen})
        rota.append(
            {
                "date": dt.isoformat(),
                "day_of_week": DOW_NAMES[dt.weekday()],
                "assignments": assignments,
            }
        )

    # Warnings: hours deviations
    warnings: list[str] = []
    for s in staff_initials:
        info = staff_by_initials[s]
        target_total = info.get("target_weekly_hours", 0) * weeks
        actual_h = 0
        for di in range(n_days):
            for t in SHIFT_TYPES:
                if solver.Value(x[s][di][t]) == 1:
                    actual_h += SHIFT_HOURS[t]
        if actual_h != target_total:
            warnings.append(
                f"{s} assigned {actual_h}h vs target {target_total}h over {weeks}w"
            )

    soft_score = int(solver.ObjectiveValue()) if penalty_terms else 0

    return {
        "success": True,
        "rota": rota,
        "warnings": warnings,
        "soft_violations_score": soft_score,
        "solve_time_ms": elapsed_ms,
        "solver_status": solver.StatusName(status),
    }


# ---------------------------------------------------------------------------
# Failure diagnostics
# ---------------------------------------------------------------------------
def _build_failure_response(
    status: int,
    payload: dict,
    elapsed_ms: int,
    forced_cells: dict,
) -> dict[str, Any]:
    """Produce a useful 'why no solution' response when the solver fails."""
    name_map = {
        cp_model.UNKNOWN: "UNKNOWN",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.INFEASIBLE: "INFEASIBLE",
    }
    status_name = name_map.get(status, str(status))

    # Quick feasibility analysis: per day, compute available staff for cover
    start_date = _parse_date(payload["rota_start_date"])
    weeks = int(payload.get("weeks", 4))
    days = _date_range(start_date, weeks)
    staff_list = payload["staff"]
    staff_by_initials = {s["initials"]: s for s in staff_list}

    blocking: list[dict[str, Any]] = []

    for dt in days:
        d_str = dt.isoformat()
        # Determine staff who are forced unavailable that day (AL / TRN)
        unavailable = set()
        forced_shift = {}
        for (init, d), shift in forced_cells.items():
            if d == d_str:
                forced_shift[init] = shift
                if shift in {"AL", "TRN", "OFF"}:
                    unavailable.add(init)
        available = [
            s for s in staff_by_initials.values()
            if s["initials"] not in unavailable
        ]
        day_capable = [s for s in available if s.get("can_do_days")]
        night_capable = [s for s in available if s.get("can_do_nights") or s.get("can_do_sleepover")]
        med_day = [s for s in day_capable if s.get("medication_competent")]
        med_night = [s for s in night_capable if s.get("medication_competent")]
        fa_day = [s for s in day_capable if s.get("first_aider")]
        fa_night = [s for s in night_capable if s.get("first_aider")]

        problems = []
        if len(day_capable) < 2:
            problems.append(f"only {len(day_capable)} day-capable staff available (need 2)")
        if len(night_capable) < 2:
            problems.append(f"only {len(night_capable)} night-capable staff available (need 2)")
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
        reason = (
            f"{first['day_of_week']} {first['date']}: "
            + "; ".join(first["problems"])
        )
    else:
        reason = (
            f"Solver returned {status_name}. Constraints are mutually unsatisfiable "
            "but no single-day blocker detected — likely a multi-day conflict "
            "(e.g. consecutive-shift / weekly-hours interactions)."
        )

    return {
        "success": False,
        "reason": reason,
        "blocking_constraints": blocking,
        "solver_status": status_name,
        "solve_time_ms": elapsed_ms,
    }
