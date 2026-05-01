"""Single source of truth for rota rule metadata.

Used by:
    - /backend/solver/rota_solver.py — to know which rules to encode as CP-SAT constraints
    - /backend/solver/rota_validator.py — to iterate and check rules on a fully-assigned rota
    - /backend/db_seeder.py — to seed initial rules_config doc

Each rule has:
    id              stable key
    name            human-readable label
    description     short blurb shown in /rules UI
    severity_default  "hard" | "soft" | "off"
    immovable       True if mode cannot be changed by user
    weight_default  used when severity = soft
"""

from __future__ import annotations

RULES: list[dict] = [
    {
        "id": "day_cover",
        "name": "Day cover: 2 staff (2D or D+D*)",
        "description": "Each calendar day must have exactly two day-shift staff.",
        "severity_default": "hard",
        "immovable": True,
        "weight_default": 0,
    },
    {
        "id": "night_cover",
        "name": "Night cover: D*+N or *+N (never 2N)",
        "description": "Each night needs one waking-night plus one sleepover; never two N.",
        "severity_default": "hard",
        "immovable": True,
        "weight_default": 0,
    },
    {
        "id": "no_n_to_d",
        "name": "No N → D back-to-back",
        "description": "Staff cannot work a day shift the morning after a waking night.",
        "severity_default": "hard",
        "immovable": True,
        "weight_default": 0,
    },
    {
        "id": "no_dstar_to_dstar",
        "name": "No D* → D* back-to-back",
        "description": "Sleepover-day shifts cannot be consecutive.",
        "severity_default": "hard",
        "immovable": True,
        "weight_default": 0,
    },
    {
        "id": "no_sleepover_before_leave",
        "name": "No sleepover before AL / training",
        "description": "A D* or * shift extends into the morning of the next day, so staff cannot start annual leave or training straight after a sleepover.",
        "severity_default": "hard",
        "immovable": True,
        "weight_default": 0,
    },
    {
        "id": "med_competent_required",
        "name": "Medication-competent on every shift",
        "description": "Every day shift and every night shift includes ≥1 medication-competent staff.",
        "severity_default": "hard",
        "immovable": False,
        "weight_default": 5000,
    },
    {
        "id": "first_aider_required",
        "name": "First-aider on every shift",
        "description": "Every day shift and every night shift includes ≥1 first-aider.",
        "severity_default": "hard",
        "immovable": False,
        "weight_default": 5000,
    },
    {
        "id": "no_male_pair_alone",
        "name": "Male staff cannot be alone together",
        "description": "If any male staff is on a shift, at least one female must be on the same shift.",
        "severity_default": "hard",
        "immovable": False,
        "weight_default": 5000,
    },
    {
        "id": "manager_no_shifts",
        "name": "Manager (J.C.) does not work shifts",
        "description": "Admin-only staff are excluded from rota shifts unless explicitly locked.",
        "severity_default": "hard",
        "immovable": False,
        "weight_default": 100000,
    },
    {
        "id": "contracted_hours_min",
        "name": "Every staff hits contracted hours",
        "description": "Total scheduled hours ≥ target − leave/training hours (−2h tolerance).",
        "severity_default": "hard",
        "immovable": False,
        "weight_default": 50,
    },
    {
        "id": "capability_flags",
        "name": "Capability flags honoured",
        "description": "Staff are only assigned shifts they are flagged for.",
        "severity_default": "hard",
        "immovable": True,
        "weight_default": 0,
    },
    {
        "id": "locked_cells_preserved",
        "name": "Locked cells preserved",
        "description": "Cells marked locked by the manager keep their assignment.",
        "severity_default": "hard",
        "immovable": True,
        "weight_default": 0,
    },
    {
        "id": "sleepover_preference",
        "name": "Sleepover-capable staff prefer D*",
        "description": "When a sleepover-capable staff is on a day shift, prefer D* over D.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 5,
    },
    {
        "id": "preferred_off_days",
        "name": "Honour staff day-of-week preferences",
        "description": "Avoid scheduling staff on their preferred-off days.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 20,
    },
    {
        "id": "avoid_pairs",
        "name": "Avoid pairing flagged staff",
        "description": "Avoid placing 'do not pair' staff together on the same shift.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 30,
    },
    {
        "id": "weekend_fairness",
        "name": "Fair distribution of weekends off",
        "description": "Spread weekend shifts proportionally to contracted hours.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 10,
    },
    {
        "id": "overtime_prefer_flexi",
        "name": "Overtime preference → flexi staff",
        "description": "When extra hours are needed above contracted minimums, prefer giving them to staff with the Flexi role (auto-detected). Use staff_initials_override to narrow it further.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 15,
        "params_default": {
            "applies_to_role": "Flexi",
            "staff_initials_override": [],
            "weekly_cap": 48,
        },
    },
    {
        "id": "prefer_dstar_over_star",
        "name": "Prefer D* over * on night cover",
        "description": "When the night sleepover slot can be filled by either D* (a day-staff who sleeps in) or * (sleepover-only), prefer D* — only use * when D* is infeasible.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 200,
    },
    {
        "id": "non_flexi_overage",
        "name": "Non-flexi staff stay near contracted hours",
        "description": "Penalty for assigning non-flexi staff above their contracted weekly hours + 8h/week. Soft by default — switch to hard to enforce strictly (may become infeasible when a Flexi has multi-day AL). Flexi staff (see overtime preference rule) are exempt.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 50,
    },
    {
        "id": "senior_weekend_cover",
        "name": "Senior on every weekend",
        "description": "Each Saturday and Sunday must have at least one of L.M. (Deputy) or L.D. (Senior Care Support) on a D or D* shift. Rotation pattern (per week) is a soft preference.",
        "severity_default": "hard",
        "immovable": True,
        "weight_default": 0,
    },
    {
        "id": "avoid_pair_seniors",
        "name": "Avoid pairing L.M. and L.D. on the same shift",
        "description": "Manager prefers to split L.M. and L.D. so each pairs with other staff. Penalty when both are on the same working day (D or D*).",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 40,
    },
    {
        "id": "min_sleepover_per_week_for_seniors",
        "name": "Minimum D* per week (per-staff)",
        "description": "Per-staff floor on D* (sleepover-day) shifts each week. Default: L.M./L.D. ≥ 2 (their core weekday rhythm), T.D. ≥ 1. Manager can edit the per-staff minimums via Rules UI. Skips weeks where staff has ≥5 AL/TRN days.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 400,
        "params_default": {
            "rules": [
                {"staff_initials": ["L.M.", "L.D."], "min_per_week": 2},
                {"staff_initials": ["T.D."], "min_per_week": 1},
            ],
        },
    },
    {
        "id": "max_one_per_role_on_al",
        "name": "Max 1 staff per role on AL same date",
        "description": "Two staff sharing the same role (e.g. two Flexi or two Night Support) cannot be on annual leave on the same date. Single-occupant roles (Manager, Deputy) are unaffected. Enforced at the leave-creation endpoint with HTTP 422 and rechecked by the validator on every rota.",
        "severity_default": "hard",
        "immovable": True,
        "weight_default": 0,
    },
    {
        "id": "senior_monday_cover",
        "name": "Senior on every Monday",
        "description": "Each Monday should have at least one senior (default L.M. or L.D.) on a working shift. Soft default with strong weight — manager can flip to Hard for strict enforcement.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 60,
        "params_default": {
            "staff_initials": ["L.M.", "L.D."],
        },
    },
    {
        "id": "respect_shift_preference",
        "name": "Respect each staff's day/night preference",
        "description": "Staff who can do BOTH day and night shifts can express a preference. The solver nudges them toward their preferred shift but still uses them for the other when needed for cover or hours.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 80,
    },
    {
        "id": "avoid_star_then_night",
        "name": "Avoid sleepover-only (*) followed by waking night (N)",
        "description": "After a `*` shift the staff has spent the night in the home and going straight into a `N` the next day is undesirable. Penalises every (*, N) pair the next day.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 25,
    },
    {
        "id": "avoid_star_then_day",
        "name": "Avoid sleepover-only (*) followed by day shift (D)",
        "description": "After `*` the staff has just slept at the home and a D the next day cuts into their rest. Per-staff overrides allow a stronger weight for staff who especially dislike this pattern (e.g. L.D.).",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 20,
        "params_default": {
            "general_weight": 20,
            "staff_overrides": {"L.D.": 60, "L.M.": 60},
        },
    },
    {
        "id": "avoid_star_for_staff",
        "name": "Avoid sleepover-only (*) for specific staff",
        "description": "Listed staff do not like working a bare `*` (sleepover-only, no day shift). They're fine with D or D*, but `*` alone is unwanted. Soft penalty per `*` assigned to them.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 50,
        "params_default": {
            "staff_initials": ["L.M.", "L.D.", "T.D."],
        },
    },
    {
        "id": "max_sleepover_per_week",
        "name": "Maximum sleepovers (D*) per week (cap)",
        "description": "For each listed staff, cap the number of D* shifts per week. Soft penalty per D* above the configured maximum. Useful for staff who only want one sleepover-day each week (e.g. T.D. → max 1).",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 80,
        "params_default": {
            "rules": [
                {"staff_initials": ["T.D."], "max_per_week": 1},
            ],
        },
    },
    {
        "id": "fair_star_distribution",
        "name": "Fair distribution of `*` (sleepover-only) shifts",
        "description": "Spread `*` shifts evenly across eligible staff (those with can_do_sleepover=true, excluding staff on avoid_star_for_staff list). Penalises the spread (max − min) of `*` count per eligible staff over the rota.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 30,
    },
    {
        "id": "weekday_weekend_split",
        "name": "Weekday / weekend split per week",
        "description": "Per-staff target count of working shifts on weekdays (Mon-Fri) AND weekend days (Sat-Sun) per week. Useful for staff who prefer e.g. exactly 1 weekday and 1 weekend shift each week (J.R.'s default). Auto-skips a sub-window when 0 days are available (AL / TRN cover the whole sub-window).",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 40,
        "params_default": {
            "rules": [
                {
                    "staff_initials": ["J.R."],
                    "weekday_target": 1,
                    "weekend_target": 1,
                    "shift_types": ["N"],
                },
            ],
        },
    },
    {
        "id": "pair_companion_on_day",
        "name": "Pair a focal staff with a companion on a specific weekday",
        "description": "If the focal staff works a day shift on the configured weekday (e.g. C.E. on Wed), at least one of the listed companions must also be working a day shift that same day. Auto-skips when the focal is on AL/TRN that date or when all companions are on AL/TRN.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 200,
        "params_default": {
            "rules": [
                {
                    "staff_initials": "C.E.",
                    "companion_initials": ["L.M.", "L.D.", "D.A."],
                    "day_of_week": "Wed",
                    "shift_types": ["D", "D*"],
                },
            ],
        },
    },
]

RULES_BY_ID = {r["id"]: r for r in RULES}


def default_rules_config() -> dict:
    """Return the default rules_config doc used by the seeder."""
    out = {}
    for r in RULES:
        entry = {
            "mode": r["severity_default"],
            "weight": r["weight_default"],
            "immovable": r["immovable"],
        }
        if r.get("params_default"):
            entry["params"] = dict(r["params_default"])
        out[r["id"]] = entry
    return out
