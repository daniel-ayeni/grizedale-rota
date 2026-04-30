"""Idempotent Mongo seed-on-boot for Grizedale rota app.

Creates these collections if missing/empty:
    users          — one admin from .env (ADMIN_EMAIL / ADMIN_PASSWORD)
    staff          — 8 Grizedale staff from seed/grizedale.json
    service_users  — 7 placeholder service users
    rules_config   — single doc (uses rule_definitions.default_rules_config)
    settings       — single doc with home name, shift hours, holidays etc
    rotas          — one previous published rota (so "copy from previous" works)

Also runs a per-boot MIGRATION:
    - Force-set C.E.first_aider=true if currently false (Phase 1 polish:
      C.E. is the female nights-capable FA; resolves night-FA gap).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from auth import hash_password
from solver.rota_solver import solve_rota
from solver.rule_definitions import default_rules_config

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
SEED_FILE = ROOT / "seed" / "grizedale.json"

UK_2026_HOLIDAYS = [
    {"date": "2026-01-01", "name": "New Year's Day"},
    {"date": "2026-04-03", "name": "Good Friday"},
    {"date": "2026-04-06", "name": "Easter Monday"},
    {"date": "2026-05-04", "name": "Early May Bank Holiday"},
    {"date": "2026-05-25", "name": "Spring Bank Holiday"},
    {"date": "2026-08-31", "name": "Summer Bank Holiday"},
    {"date": "2026-12-25", "name": "Christmas Day"},
    {"date": "2026-12-28", "name": "Boxing Day (substitute)"},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def seed_if_empty(db) -> dict:
    summary = {}

    # Indexes
    await db.users.create_index("email", unique=True)
    await db.staff.create_index("initials", unique=True)
    await db.leave.create_index([("staff_initials", 1), ("date", 1)], unique=True)
    await db.request_tokens.create_index("token", unique=True)
    await db.rotas.create_index("start_date")

    # users
    if await db.users.count_documents({}) == 0:
        admin_email = os.environ.get("ADMIN_EMAIL", "manager@grizedale.local")
        admin_password = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")
        admin = {
            "id": str(uuid.uuid4()),
            "email": admin_email.lower(),
            "name": "Manager (seed)",
            "role": "admin",
            "password_hash": hash_password(admin_password),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.users.insert_one(admin)
        logger.warning(
            "Seed admin created: email=%s password=%s — CHANGE IT after first login",
            admin_email, admin_password,
        )
        summary["users"] = 1

    # staff
    if await db.staff.count_documents({}) == 0 and SEED_FILE.exists():
        seed = json.loads(SEED_FILE.read_text())
        docs = []
        for s in seed["staff"]:
            doc = dict(s)
            doc["id"] = str(uuid.uuid4())
            doc["active"] = True
            doc["created_at"] = _now_iso()
            doc["updated_at"] = _now_iso()
            docs.append(doc)
        await db.staff.insert_many(docs)
        summary["staff"] = len(docs)

    # MIGRATION: ensure C.E. is first_aider=true (Phase 1 polish)
    res = await db.staff.update_one(
        {"initials": "C.E.", "first_aider": {"$ne": True}},
        {"$set": {"first_aider": True, "updated_at": _now_iso()}},
    )
    if res.modified_count > 0:
        logger.info("Migration: set C.E.first_aider=true (was false)")
        summary["migration_ce_fa"] = res.modified_count

    # MIGRATION: ensure J.R. has can_do_sleepover=false (Phase 2 user feedback)
    res = await db.staff.update_one(
        {"initials": "J.R.", "can_do_sleepover": {"$ne": False}},
        {"$set": {"can_do_sleepover": False, "updated_at": _now_iso()}},
    )
    if res.modified_count > 0:
        logger.info("Migration: set J.R.can_do_sleepover=false")
        summary["migration_jr_sleepover"] = res.modified_count

    # MIGRATION: ensure rules_config has overtime_prefer_flexi entry
    rules_doc = await db.rules_config.find_one({}, {"_id": 0})
    if rules_doc:
        rules = rules_doc.get("rules") or {}
        from solver.rule_definitions import RULES_BY_ID
        for rule_id in ("overtime_prefer_flexi", "prefer_dstar_over_star", "non_flexi_overage"):
            if rule_id in rules:
                continue
            r_def = RULES_BY_ID[rule_id]
            new_entry = {
                "mode": r_def["severity_default"],
                "weight": r_def["weight_default"],
                "immovable": r_def["immovable"],
            }
            if r_def.get("params_default"):
                new_entry["params"] = dict(r_def["params_default"])
            await db.rules_config.update_one(
                {},
                {"$set": {f"rules.{rule_id}": new_entry, "updated_at": _now_iso()}},
            )
            logger.info("Migration: added %s rule to rules_config", rule_id)
            summary[f"migration_rule_{rule_id}"] = 1

        # MIGRATION: bump stale defaults from earlier Phase 2 commits to
        # current values (only updates if still at old default).
        stale_bumps = [
            ("prefer_dstar_over_star", "weight", 25, 200),
            ("non_flexi_overage", "mode", "soft", "hard"),
        ]
        for rid, field, old_val, new_val in stale_bumps:
            res = await db.rules_config.update_one(
                {f"rules.{rid}.{field}": old_val},
                {"$set": {f"rules.{rid}.{field}": new_val, "updated_at": _now_iso()}},
            )
            if res.modified_count > 0:
                logger.info("Migration: bumped rules.%s.%s from %s -> %s", rid, field, old_val, new_val)
                summary[f"migration_bump_{rid}_{field}"] = 1

    # service users (7 placeholders)
    if await db.service_users.count_documents({}) == 0:
        placeholders = []
        for i in range(1, 8):
            placeholders.append({
                "id": str(uuid.uuid4()),
                "name": f"Service User {i}",
                "notes": "",
                "needs_female_staff": False,
                "needs_med_competent_present": False,
                "active": True,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            })
        await db.service_users.insert_many(placeholders)
        summary["service_users"] = len(placeholders)

    # rules_config (single doc)
    if await db.rules_config.count_documents({}) == 0:
        rules_doc = {
            "id": "rules_singleton",
            "rules": default_rules_config(),
            "updated_at": _now_iso(),
        }
        await db.rules_config.insert_one(rules_doc)
        summary["rules_config"] = 1

    # settings (single doc)
    if await db.settings.count_documents({}) == 0:
        settings = {
            "id": "settings_singleton",
            "home_name": "Grizedale",
            "rota_length_weeks": 4,
            "rota_start_day": "Mon",
            "shift_hours": {"D": 12, "D*": 14, "N": 12, "*": 0, "OFF": 0, "AL": 0, "TRN": 0},
            "theme_default": "paper",
            "public_holidays": UK_2026_HOLIDAYS,
            "rota_start_date_default": "2026-04-20",
            "updated_at": _now_iso(),
        }
        await db.settings.insert_one(settings)
        summary["settings"] = 1

    # rotas — seed ONE previous published rota (so "copy from previous"
    # has data to copy on day one). Dated 4 weeks before the default start.
    if await db.rotas.count_documents({}) == 0:
        try:
            previous = await _generate_previous_rota(db)
            if previous:
                await db.rotas.insert_one(previous)
                summary["rotas"] = 1
                logger.info("Seeded previous published rota %s", previous["start_date"])
        except Exception as exc:
            logger.exception("Failed to seed previous rota: %s", exc)

    return summary


async def _generate_previous_rota(db) -> dict | None:
    """Generate a previous published rota using the solver."""
    settings = await db.settings.find_one({}, {"_id": 0}) or {}
    staff_docs = await db.staff.find({"active": True}, {"_id": 0}).to_list(1000)

    default_start = settings.get("rota_start_date_default", "2026-04-20")
    weeks = int(settings.get("rota_length_weeks", 4))
    prev_start_dt = datetime.strptime(default_start, "%Y-%m-%d") - timedelta(weeks=weeks)
    prev_start = prev_start_dt.strftime("%Y-%m-%d")

    payload = {
        "rota_start_date": prev_start,
        "weeks": weeks,
        "staff": [{k: s.get(k) for k in (
            "initials", "full_name", "role", "gender",
            "target_weekly_hours", "is_admin_only",
            "medication_competent", "first_aider", "fire_trained",
            "trust_level", "can_do_days", "can_do_nights", "can_do_sleepover",
            "manager_weekday_admin", "preferred_off_days",
        )} for s in staff_docs],
        "leave": [],
        "locked_cells": [],
        "rules": {
            "first_aider_required": "hard",
            "med_competent_required": "hard",
            "no_male_pair_alone": "hard",
            "manager_no_shifts": "hard",
            "contracted_hours_min": "hard",
            "sleepover_preference": "soft",
        },
    }
    result = solve_rota(payload, time_limit_s=10)
    if not result.get("success"):
        logger.warning("Previous-rota solve failed: %s", result.get("reason"))
        return None

    assignments = []
    for day in result["rota"]:
        for a in day["assignments"]:
            assignments.append({
                "date": day["date"],
                "staff_initials": a["staff_initials"],
                "shift": a["shift"],
                "locked": False,
            })

    return {
        "id": str(uuid.uuid4()),
        "start_date": prev_start,
        "weeks": weeks,
        "assignments": assignments,
        "on_call": [],
        "status": "published",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "created_by": "seed",
        "title": f"Grizedale Monthly {prev_start}",
    }
