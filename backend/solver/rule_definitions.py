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
        "name": "Senior / day staff minimum sleepovers per week",
        "description": "Each listed staff should work at least N D* shifts every week. Soft by default — rotation usually satisfies this naturally. Manager can override by removing the staff from the list or lowering N.",
        "severity_default": "soft",
        "immovable": False,
        "weight_default": 30,
        "params_default": {
            "staff_initials": ["L.M.", "L.D.", "T.D."],
            "min_sleepovers_per_week": 1,
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
