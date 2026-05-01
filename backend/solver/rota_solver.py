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
    "min_sleepover_per_week_for_seniors": 30,  # penalty per week per listed staff with < min D*
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
}

SENIOR_STAFF = ("L.M.", "L.D.")


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

    # Manager hard rule: J.C. (or any is_admin_only) cannot work shifts
    # unless cell is locked.
    if modes["manager_no_shifts"] == "hard":
        for s in staff_inits:
            info = staff_by[s]
            if not info.get("is_admin_only"):
                continue
            for di in range(n_days):
                d_str = days[di].isoformat()
                if (s, d_str) in forced_cells:
                    continue  # locked override allowed
                for t in WORKING_SHIFTS:
                    model.Add(x[s][di][t] == 0)

    # Daily cover constraints
    for di in range(n_days):
        cD = sum(x[s][di]["D"] for s in staff_inits)
        cDs = sum(x[s][di]["D*"] for s in staff_inits)
        cN = sum(x[s][di]["N"] for s in staff_inits)
        cStar = sum(x[s][di]["*"] for s in staff_inits)

        # Day cover: 2D OR 1D + 1D* (always hard)
        model.Add(cD + cDs == 2)
        model.Add(cDs <= 1)
        # Night cover: D*+N OR *+N (always hard)
        model.Add(cN == 1)
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

            if is_flexi:
                # Split this week's overage into rewardable + above-cap
                over_reward_w = model.NewIntVar(0, max(cap_overage_weekly, 1), f"ot_reward_{s}_w{w}")
                over_above_w = model.NewIntVar(0, 200, f"ot_above_{s}_w{w}")
                model.Add(over_reward_w + over_above_w == over_w)
                if cap_overage_weekly > 0:
                    soft_terms.append(-weights["overtime_prefer_flexi"] * over_reward_w)
                # Above 48h/week: strong penalty same as non-flexi
                soft_terms.append(weights["non_flexi_overage"] * over_above_w)
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
    present_seniors = [s for s in SENIOR_STAFF if s in staff_by]
    if senior_mode != "off" and present_seniors:
        for di, dt in enumerate(days):
            if dt.weekday() >= 5:  # Sat=5, Sun=6
                cover_sum = sum(
                    x[sr][di]["D"] + x[sr][di]["D*"] for sr in present_seniors
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
    # avoid_pair_seniors: penalty when BOTH L.M. and L.D. are on day cover
    # (D or D*) on the same date. Manager prefers each senior to pair with
    # other staff.
    # -----------------------------------------------------------------
    aps_mode = modes.get("avoid_pair_seniors", "soft")
    if aps_mode != "off" and all(s in staff_by for s in SENIOR_STAFF):
        a, b = SENIOR_STAFF
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
    # min_sleepover_per_week_for_seniors: each listed staff should have
    # >= N D* shifts per week. Soft by default. Skips weeks where the
    # staff is fully on AL/TRN (≥5 days), since no D* is physically
    # possible in that case.
    # -----------------------------------------------------------------
    msl_mode = modes.get("min_sleepover_per_week_for_seniors", "soft")
    if msl_mode != "off":
        msl_params = rule_params.get("min_sleepover_per_week_for_seniors") or {}
        msl_staff = [s for s in (msl_params.get("staff_initials") or ["L.M.", "L.D.", "T.D."])
                     if s in staff_by]
        msl_min = max(0, int(msl_params.get("min_sleepovers_per_week", 1)))
        if msl_min > 0 and msl_staff:
            for s in msl_staff:
                for w in range(weeks):
                    week_idx = range(w * 7, (w + 1) * 7)
                    dstar_w = sum(x[s][di]["D*"] for di in week_idx)
                    # Count AL+TRN to skip weeks where the staff is unavailable.
                    unavail_w = sum(x[s][di]["AL"] + x[s][di]["TRN"] for di in week_idx)
                    if msl_mode == "hard":
                        # hard: dstar_w + (unavail_w >= 5 ? large : 0) >= msl_min.
                        # Use an indicator for "mostly unavailable".
                        mostly_off = model.NewBoolVar(f"msl_off_{s}_w{w}")
                        model.Add(unavail_w >= 5).OnlyEnforceIf(mostly_off)
                        model.Add(unavail_w <= 4).OnlyEnforceIf(mostly_off.Not())
                        # When NOT mostly_off, require dstar_w >= msl_min
                        model.Add(dstar_w >= msl_min).OnlyEnforceIf(mostly_off.Not())
                    else:  # soft
                        # penalty = 1 if dstar_w < msl_min AND unavail_w < 5
                        short = model.NewBoolVar(f"msl_short_{s}_w{w}")
                        available = model.NewBoolVar(f"msl_avail_{s}_w{w}")
                        # available = (unavail_w <= 4)
                        model.Add(unavail_w <= 4).OnlyEnforceIf(available)
                        model.Add(unavail_w >= 5).OnlyEnforceIf(available.Not())
                        # not_enough = (dstar_w < msl_min)
                        not_enough = model.NewBoolVar(f"msl_ne_{s}_w{w}")
                        model.Add(dstar_w <= msl_min - 1).OnlyEnforceIf(not_enough)
                        model.Add(dstar_w >= msl_min).OnlyEnforceIf(not_enough.Not())
                        # short = available AND not_enough
                        model.AddBoolAnd([available, not_enough]).OnlyEnforceIf(short)
                        model.AddBoolOr([available.Not(), not_enough.Not()]).OnlyEnforceIf(short.Not())
                        soft_terms.append(weights["min_sleepover_per_week_for_seniors"] * short)

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
        # Manager treated as unavailable for solver purposes
        avail_for_shifts = [s for s in avail if not s.get("is_admin_only")]
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
