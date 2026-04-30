"""Idempotent Mongo seed-on-boot for Grizedale rota app (Phase 1).

Creates these collections if missing/empty:
    users          — one admin from .env (ADMIN_EMAIL / ADMIN_PASSWORD)
    staff          — 8 Grizedale staff from seed/grizedale.json
    service_users  — 7 placeholder service users
    rules_config   — single doc with rule modes / weights
    settings       — single doc with home name, shift hours, holidays etc
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from auth import hash_password

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
            "rules": {
                "day_cover":             {"mode": "hard", "weight": 0,   "immovable": True},
                "night_cover":           {"mode": "hard", "weight": 0,   "immovable": True},
                "med_competent_required": {"mode": "hard", "weight": 5000},
                "first_aider_required":   {"mode": "hard", "weight": 5000},
                "no_male_pair_alone":     {"mode": "hard", "weight": 5000},
                "no_n_to_d":             {"mode": "hard", "weight": 0,   "immovable": True},
                "no_dstar_to_dstar":     {"mode": "hard", "weight": 0,   "immovable": True},
                "manager_no_shifts":     {"mode": "hard", "weight": 100000},
                "contracted_hours_min":  {"mode": "hard", "weight": 50},
                "sleepover_preference":  {"mode": "soft", "weight": 5},
                "preferred_off_days":    {"mode": "soft", "weight": 20},
                "avoid_pairs":           {"mode": "soft", "weight": 30},
                "weekend_fairness":      {"mode": "soft", "weight": 10},
            },
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

    return summary
