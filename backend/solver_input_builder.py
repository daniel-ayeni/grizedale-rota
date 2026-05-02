"""Build the solver-input payload from the live MongoDB state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# Keys we keep on each staff record before sending to the solver
_STAFF_FIELDS = (
    "initials", "full_name", "role", "gender",
    "target_weekly_hours", "is_admin_only",
    "medication_competent", "first_aider", "fire_trained",
    "trust_level",
    "can_do_days", "can_do_nights", "can_do_sleepover",
    "manager_weekday_admin",
    "preferred_off_days",
    "accepts_overtime",
    "shift_preference",
    # Role flags — solver derives senior/manager/flexi lists from these
    # instead of hard-coded initials.
    "is_manager", "is_deputy", "is_senior", "is_flexi", "is_night",
)


def _extract_staff_for_solver(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: doc.get(k) for k in _STAFF_FIELDS}


def _rules_to_solver_modes(rules_config: dict[str, Any]) -> dict[str, str]:
    rules = rules_config.get("rules", {}) if rules_config else {}
    out = {}
    for key, val in rules.items():
        if isinstance(val, dict) and "mode" in val:
            out[key] = val["mode"]
    return out


def _rules_to_solver_weights(rules_config: dict[str, Any]) -> dict[str, int]:
    rules = rules_config.get("rules", {}) if rules_config else {}
    out: dict[str, int] = {}
    for key, val in rules.items():
        if isinstance(val, dict) and "weight" in val and isinstance(val["weight"], (int, float)):
            out[key] = int(val["weight"])
    return out


def _rules_to_solver_params(rules_config: dict[str, Any]) -> dict[str, dict]:
    rules = rules_config.get("rules", {}) if rules_config else {}
    out: dict[str, dict] = {}
    for key, val in rules.items():
        if isinstance(val, dict) and isinstance(val.get("params"), dict):
            out[key] = val["params"]
    return out


async def build_solver_payload(db, override_start_date: str | None = None) -> dict[str, Any]:
    """Read staff / rules / settings from Mongo and build the solver input."""
    staff_docs = await db.staff.find({"active": True}, {"_id": 0}).to_list(1000)
    settings = await db.settings.find_one({}, {"_id": 0}) or {}
    rules_doc = await db.rules_config.find_one({}, {"_id": 0}) or {}
    leave_docs = await db.leave.find({}, {"_id": 0}).to_list(10000) if "leave" in await db.list_collection_names() else []

    return {
        "rota_start_date": override_start_date or settings.get("rota_start_date_default") or datetime.now(timezone.utc).date().isoformat(),
        "weeks": settings.get("rota_length_weeks", 4),
        "staff": [_extract_staff_for_solver(s) for s in staff_docs],
        "leave": leave_docs,
        "locked_cells": [],
        "on_call": [],
        "avoid_pairs": [],
        "rules": _rules_to_solver_modes(rules_doc),
        "rule_weights": _rules_to_solver_weights(rules_doc),
        "rule_params": _rules_to_solver_params(rules_doc),
        "shift_hours": settings.get("shift_hours") or {},
        "senior_weekend_rotation": settings.get("senior_weekend_rotation") or [],
    }
