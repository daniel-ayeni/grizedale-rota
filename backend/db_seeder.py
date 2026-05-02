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

    # MIGRATION: J.R. target_weekly_hours 28 → 24 (per user spec)
    res_jr = await db.staff.update_one(
        {"initials": "J.R.", "target_weekly_hours": 28},
        {"$set": {"target_weekly_hours": 24, "updated_at": _now_iso()}},
    )
    if res_jr.modified_count > 0:
        logger.info("Migration: J.R. target_weekly_hours 28 -> 24")
        summary["migration_jr_target_24h"] = res_jr.modified_count

    # MIGRATION: ensure J.R. has can_do_sleepover=false (Phase 2 user feedback)
    res = await db.staff.update_one(
        {"initials": "J.R.", "can_do_sleepover": {"$ne": False}},
        {"$set": {"can_do_sleepover": False, "updated_at": _now_iso()}},
    )
    if res.modified_count > 0:
        logger.info("Migration: set J.R.can_do_sleepover=false")
        summary["migration_jr_sleepover"] = res.modified_count

    # MIGRATION: backfill `accepts_overtime` flag — D.A. only opts in by
    # default (per user); everyone else opts out. Only touches staff that
    # don't already have the field set so manager edits aren't reverted.
    res_da = await db.staff.update_one(
        {"initials": "D.A.", "accepts_overtime": {"$exists": False}},
        {"$set": {"accepts_overtime": True, "updated_at": _now_iso()}},
    )
    res_others = await db.staff.update_many(
        {"initials": {"$ne": "D.A."}, "accepts_overtime": {"$exists": False}},
        {"$set": {"accepts_overtime": False, "updated_at": _now_iso()}},
    )
    if res_da.modified_count + res_others.modified_count > 0:
        logger.info(
            "Migration: backfilled accepts_overtime (D.A.=true, others=false): "
            "%d D.A. + %d others",
            res_da.modified_count, res_others.modified_count,
        )
        summary["migration_accepts_overtime"] = (
            res_da.modified_count + res_others.modified_count
        )

    # MIGRATION: backfill `shift_preference` field — default everyone to
    # "no_preference". Manager sets explicit prefs from /staff page.
    res_pref = await db.staff.update_many(
        {"shift_preference": {"$exists": False}},
        {"$set": {"shift_preference": "no_preference", "updated_at": _now_iso()}},
    )
    if res_pref.modified_count > 0:
        logger.info("Migration: backfilled shift_preference=no_preference on %d staff", res_pref.modified_count)
        summary["migration_shift_preference"] = res_pref.modified_count

    # MIGRATION: role flags. De-hardcode solver constraints that
    # previously referenced "J.C.", "L.M.", "L.D." etc. by literal
    # initials. Flags are on the staff doc so managers can promote /
    # demote without touching code.
    role_flag_defaults = {
        "J.C.": {"is_manager": True,  "is_deputy": False, "is_senior": False, "is_flexi": False, "is_night": False},
        "L.M.": {"is_manager": False, "is_deputy": True,  "is_senior": True,  "is_flexi": False, "is_night": False},
        "L.D.": {"is_manager": False, "is_deputy": False, "is_senior": True,  "is_flexi": False, "is_night": False},
        "D.A.": {"is_manager": False, "is_deputy": False, "is_senior": False, "is_flexi": True,  "is_night": False},
        "T.D.": {"is_manager": False, "is_deputy": False, "is_senior": False, "is_flexi": True,  "is_night": False},
        "C.E.": {"is_manager": False, "is_deputy": False, "is_senior": False, "is_flexi": False, "is_night": True},
        "A.A.": {"is_manager": False, "is_deputy": False, "is_senior": False, "is_flexi": False, "is_night": True},
        "J.R.": {"is_manager": False, "is_deputy": False, "is_senior": False, "is_flexi": False, "is_night": True},
    }
    role_flag_updates = 0
    for init, flags in role_flag_defaults.items():
        # Only fill fields that are missing — don't overwrite manager edits.
        missing_query = {"initials": init, "$or": [
            {f: {"$exists": False}} for f in flags.keys()
        ]}
        res = await db.staff.update_one(missing_query, {"$set": {**flags, "updated_at": _now_iso()}})
        role_flag_updates += res.modified_count
    # Anyone not in the canonical list gets defaults where missing.
    default_flags = {"is_manager": False, "is_deputy": False, "is_senior": False, "is_flexi": False, "is_night": False}
    for flag, val in default_flags.items():
        res = await db.staff.update_many(
            {flag: {"$exists": False}},
            {"$set": {flag: val, "updated_at": _now_iso()}},
        )
        role_flag_updates += res.modified_count
    if role_flag_updates > 0:
        logger.info("Migration: set role flags on %d staff docs", role_flag_updates)
        summary["migration_role_flags"] = role_flag_updates

    # MIGRATION: backfill `display_order` field — match the seed JSON
    # array order (manager → deputy → seniors → flexis → nights). Both the
    # /staff page and the rota grid sort rows by display_order ASC, and
    # the PDF/Excel exports MUST match.
    canonical_order = ["J.C.", "L.M.", "L.D.", "D.A.", "T.D.", "C.E.", "A.A.", "J.R."]
    display_order_updates = 0
    for idx, init in enumerate(canonical_order):
        res = await db.staff.update_one(
            {"initials": init},
            {"$set": {"display_order": (idx + 1) * 10, "updated_at": _now_iso()}},
        )
        display_order_updates += res.modified_count
    # Anyone NOT in the canonical list (custom staff added by manager)
    # gets a default display_order at the end if missing.
    res_extra = await db.staff.update_many(
        {"display_order": {"$exists": False}},
        {"$set": {"display_order": 999, "updated_at": _now_iso()}},
    )
    display_order_updates += res_extra.modified_count
    if display_order_updates > 0:
        logger.info("Migration: assigned display_order to %d staff", display_order_updates)
        summary["migration_display_order"] = display_order_updates

    # MIGRATION: ensure rules_config has overtime_prefer_flexi entry
    rules_doc = await db.rules_config.find_one({}, {"_id": 0})
    if rules_doc:
        rules = rules_doc.get("rules") or {}
        from solver.rule_definitions import RULES_BY_ID
        for rule_id in ("overtime_prefer_flexi", "prefer_dstar_over_star", "non_flexi_overage", "no_sleepover_before_leave", "senior_weekend_cover", "avoid_pair_seniors", "min_sleepover_per_week_for_seniors", "max_one_per_role_on_al", "senior_monday_cover", "respect_shift_preference", "avoid_star_then_night", "avoid_star_then_day", "avoid_star_for_staff", "max_sleepover_per_week", "fair_star_distribution", "weekday_weekend_split", "pair_companion_on_day"):
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
            # Previously non_flexi_overage was hard; that caused infeasibility
            # when a Flexi had multi-day AL. Spec is soft (+8h preference).
            ("non_flexi_overage", "mode", "hard", "soft"),
            # Bump min_sleepover weight from 30 → 100 (legacy session) → 400.
            # 400 needed so L.D. picks 2 D* (cost 600 overage) over 1 D* +
            # missing-D* penalty (300 + 400 = 700).
            ("min_sleepover_per_week_for_seniors", "weight", 30, 400),
            ("min_sleepover_per_week_for_seniors", "weight", 100, 400),
            # Bump pair_companion_on_day from initial 50 → 200 so the
            # C.E. Wednesday companion is reliably honoured by the solver.
            ("pair_companion_on_day", "weight", 50, 200),
        ]
        for rid, field, old_val, new_val in stale_bumps:
            res = await db.rules_config.update_one(
                {f"rules.{rid}.{field}": old_val},
                {"$set": {f"rules.{rid}.{field}": new_val, "updated_at": _now_iso()}},
            )
            if res.modified_count > 0:
                logger.info("Migration: bumped rules.%s.%s from %s -> %s", rid, field, old_val, new_val)
                summary[f"migration_bump_{rid}_{field}"] = 1

        # MIGRATION: convert min_sleepover_per_week_for_seniors from old
        # shape {staff_initials, min_sleepovers_per_week} to new shape
        # {rules: [{staff_initials, min_per_week}, ...]}, AND bump
        # L.M./L.D. min from 1 → 2 (per user spec).
        msl_entry = (rules_doc.get("rules") or {}).get("min_sleepover_per_week_for_seniors") or {}
        msl_params = msl_entry.get("params") or {}
        if "rules" not in msl_params:
            await db.rules_config.update_one(
                {},
                {"$set": {
                    "rules.min_sleepover_per_week_for_seniors.params": {
                        "rules": [
                            {"staff_initials": ["L.M.", "L.D."], "min_per_week": 2},
                            {"staff_initials": ["T.D."], "min_per_week": 1},
                        ],
                    },
                    "updated_at": _now_iso(),
                }},
            )
            logger.info("Migration: refactored min_sleepover_per_week_for_seniors to per-rule shape (L.M./L.D.=2, T.D.=1)")
            summary["migration_min_sleepover_refactor"] = 1

        # MIGRATION: extend avoid_star_then_day staff_overrides to include
        # L.M. (was L.D. only). Only updates if the existing value still
        # matches the old default — manager edits are preserved.
        asd_entry = (rules_doc.get("rules") or {}).get("avoid_star_then_day") or {}
        asd_params = asd_entry.get("params") or {}
        asd_overrides = asd_params.get("staff_overrides") or {}
        if asd_overrides == {"L.D.": 60}:
            await db.rules_config.update_one(
                {},
                {"$set": {
                    "rules.avoid_star_then_day.params.staff_overrides": {
                        "L.D.": 60, "L.M.": 60,
                    },
                    "updated_at": _now_iso(),
                }},
            )
            logger.info("Migration: extended avoid_star_then_day overrides to include L.M.")
            summary["migration_avoid_star_then_day_lm"] = 1

        # MIGRATION: convert legacy overtime_prefer_flexi.params from
        # {preferred_staff_initials} → {applies_to_role, staff_initials_override}
        ot_entry = (rules_doc.get("rules") or {}).get("overtime_prefer_flexi") or {}
        ot_params = ot_entry.get("params") or {}
        if "preferred_staff_initials" in ot_params and "applies_to_role" not in ot_params:
            legacy_value = ot_params.get("preferred_staff_initials")
            new_params = {
                "applies_to_role": "Flexi",
                "staff_initials_override": [],  # leave empty so auto-detect kicks in
                "weekly_cap": int(ot_params.get("weekly_cap", 48)),
            }
            await db.rules_config.update_one(
                {},
                {"$set": {
                    "rules.overtime_prefer_flexi.params": new_params,
                    "updated_at": _now_iso(),
                }},
            )
            logger.info(
                "Migration: overtime_prefer_flexi.params converted (legacy preferred_staff_initials=%s discarded; auto-detect by role='Flexi')",
                legacy_value,
            )
            summary["migration_overtime_params"] = 1

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
        # Pass the freshly-seeded staff docs to default_rules_config so
        # role-flag-dependent rules (min_sleepover_for_seniors, etc.)
        # are pre-populated with the initials of flagged seniors. This
        # keeps the rule_definitions module free of initial literals.
        seed_staff = await db.staff.find({}, {"_id": 0}).to_list(1000)
        rules_doc = {
            "id": "rules_singleton",
            "rules": default_rules_config(seed_staff),
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
            "theme_default": "modern",
            "public_holidays": UK_2026_HOLIDAYS,
            "rota_start_date_default": "2026-04-20",
            "senior_weekend_rotation": [
                {"week_index": 1, "staff_initials": "L.M."},
                {"week_index": 2, "staff_initials": "L.D."},
                {"week_index": 3, "staff_initials": "L.M."},
                {"week_index": 4, "staff_initials": "L.D."},
            ],
            "updated_at": _now_iso(),
        }
        await db.settings.insert_one(settings)
        summary["settings"] = 1
    else:
        # MIGRATION: backfill senior_weekend_rotation on the existing settings doc
        existing = await db.settings.find_one({}, {"_id": 0})
        if existing and "senior_weekend_rotation" not in existing:
            await db.settings.update_one(
                {},
                {"$set": {
                    "senior_weekend_rotation": [
                        {"week_index": 1, "staff_initials": "L.M."},
                        {"week_index": 2, "staff_initials": "L.D."},
                        {"week_index": 3, "staff_initials": "L.M."},
                        {"week_index": 4, "staff_initials": "L.D."},
                    ],
                    "updated_at": _now_iso(),
                }},
            )
            logger.info("Migration: added senior_weekend_rotation to settings")
            summary["migration_senior_weekend_rotation"] = 1
        # MIGRATION: bump theme_default from "paper" → "modern" for any
        # existing settings doc that still has the legacy default.
        # Existing users with a localStorage theme preference are
        # unaffected (the frontend honours localStorage first).
        if existing and existing.get("theme_default") == "paper":
            await db.settings.update_one(
                {}, {"$set": {"theme_default": "modern", "updated_at": _now_iso()}},
            )
            logger.info("Migration: theme_default paper → modern")
            summary["migration_theme_default_modern"] = 1

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
