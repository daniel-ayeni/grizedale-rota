"""Grizedale Rota Builder — Phase 2 backend.

Endpoints (Phase 0/1 retained, Phase 2 added):

  /api/health                                          (no auth)
  /api/auth/login, /register, /me, /logout

  /api/staff                CRUD
  /api/service-users        CRUD
  /api/rules                GET / PUT
  /api/settings             GET / PUT
  /api/admins               list / create / delete

  /api/solver/seed                                     (live from Mongo)
  /api/solver/generate                                  (uses Mongo by default)

  /api/rotas                                           list / create
  /api/rotas/{id}                                      get / update / delete
  /api/rotas/{id}/cell                                 PATCH single cell
  /api/rotas/{id}/validate                             POST full validate
  /api/rotas/{id}/copy-from-previous                   POST

  /api/leave                                           list (filter) / create / delete
  /api/requests                                        list / create / patch / bulk
  /api/request-tokens                                  list / create / revoke

  /api/public/request-link/{token}                     GET (no auth)
  /api/public/request-link/{token}/submit              POST (no auth)
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from auth import (
    create_access_token,
    hash_password,
    make_current_user_dep,
    new_user_id,
    verify_password,
)
from db_seeder import seed_if_empty
from solver.rota_solver import solve_rota
from solver.rota_validator import summarise_violations, validate_rota
from solver_input_builder import build_solver_payload


# --- Mongo --------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]


def _get_db():
    return db


# --- App ----------------------------------------------------------------
app = FastAPI(
    title="Grizedale Rota Builder API",
    description="Phase 2 — rotas, leave, requests, public request link",
    version="0.3.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
api = APIRouter(prefix="/api")
auth_required = make_current_user_dep(_get_db)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dow_short(date_str: str) -> str:
    """Three-letter weekday for a 'YYYY-MM-DD' string. Used by lock
    pre-check error formatting so the frontend can show a friendly
    'Mon 2026-04-20' instead of a bare ISO date."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a")
    except ValueError:
        return ""


def _strip_id(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return doc
    doc.pop("_id", None)
    return doc


# --- Pydantic schemas ---------------------------------------------------
class LoginIn(BaseModel):
    email: str
    password: str


class RegisterIn(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=6)
    role: str = "admin"


class StaffIn(BaseModel):
    initials: str
    full_name: str
    role: str
    gender: str = "F"
    target_weekly_hours: int = 36
    is_admin_only: bool = False
    medication_competent: bool = False
    first_aider: bool = False
    fire_trained: bool = True
    trust_level: str = "medium"
    can_do_days: bool = True
    can_do_nights: bool = False
    can_do_sleepover: bool = False
    manager_weekday_admin: bool = False
    preferred_off_days: list[str] = []
    accepts_overtime: bool = False
    shift_preference: str = "no_preference"  # "day" | "night" | "no_preference"
    # Role flags (de-hardcoded solver lookup, editable per staff).
    is_manager: bool = False
    is_deputy: bool = False
    is_senior: bool = False
    is_flexi: bool = False
    is_night: bool = False
    active: bool = True


class StaffPatch(BaseModel):
    initials: str | None = None
    full_name: str | None = None
    role: str | None = None
    gender: str | None = None
    target_weekly_hours: int | None = None
    is_admin_only: bool | None = None
    medication_competent: bool | None = None
    first_aider: bool | None = None
    fire_trained: bool | None = None
    trust_level: str | None = None
    can_do_days: bool | None = None
    can_do_nights: bool | None = None
    can_do_sleepover: bool | None = None
    manager_weekday_admin: bool | None = None
    preferred_off_days: list[str] | None = None
    accepts_overtime: bool | None = None
    shift_preference: str | None = None
    is_manager: bool | None = None
    is_deputy: bool | None = None
    is_senior: bool | None = None
    is_flexi: bool | None = None
    is_night: bool | None = None
    active: bool | None = None


class ServiceUserIn(BaseModel):
    name: str
    notes: str = ""
    needs_female_staff: bool = False
    needs_med_competent_present: bool = False
    active: bool = True


class ServiceUserPatch(BaseModel):
    name: str | None = None
    notes: str | None = None
    needs_female_staff: bool | None = None
    needs_med_competent_present: bool | None = None
    active: bool | None = None


class RotaCreate(BaseModel):
    start_date: str
    weeks: int = 4
    title: str | None = None


class CellPatch(BaseModel):
    date: str
    staff_initials: str
    shift: str = ""
    locked: bool | None = None
    reason: str | None = None


class CellBulkUpdate(BaseModel):
    """One entry in a bulk-cell PATCH. Each field is optional so the caller
    can patch just `locked` (toggle lock without changing shift) or just
    `shift` (clear/reassign without touching lock)."""
    date: str
    staff_initials: str
    shift: str | None = None
    locked: bool | None = None
    reason: str | None = None


class CellBulkPatch(BaseModel):
    updates: list[CellBulkUpdate]
    # If true, locked cells are allowed to be modified (used by the "Unlock"
    # bulk action). If false (default), locked cells are skipped silently to
    # protect manager-locked decisions.
    force: bool = False


class LeaveBulkIn(BaseModel):
    staff_initials: str
    dates: list[str]
    type: str = "AL"
    notes: str = ""


class RequestIn(BaseModel):
    staff_initials: str
    date: str
    shift_preference: str = "OFF"
    notes: str = ""
    source: str = "manager"


class RequestPatch(BaseModel):
    status: str | None = None
    resolution_note: str | None = None
    override_conflict: bool = False
    override_reason: str | None = None


class RequestBulkPatch(BaseModel):
    ids: list[str]
    status: str
    resolution_note: str | None = None
    override_conflict: bool = False
    override_reason: str | None = None


class TokenCreate(BaseModel):
    staff_initials: str
    expires_in_days: int = 30


class PublicSubmitIn(BaseModel):
    requests: list[dict[str, Any]]


# ============================================================================
# Health
# ============================================================================
@api.get("/")
async def root():
    return {"message": "Grizedale Rota Builder API — Phase 2"}


@api.get("/health")
async def health():
    return {"status": "ok"}


# ============================================================================
# Auth
# ============================================================================
@api.post("/auth/login")
async def login(payload: LoginIn):
    user = await db.users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user["id"], user["email"])
    safe = {k: v for k, v in user.items() if k not in {"_id", "password_hash"}}
    return {"token": token, "user": safe}


@api.post("/auth/register")
async def register(payload: RegisterIn, current=Depends(auth_required)):
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {
        "id": new_user_id(), "email": email, "name": payload.name,
        "role": payload.role or "admin",
        "password_hash": hash_password(payload.password),
        "created_at": _now(), "updated_at": _now(),
    }
    await db.users.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "password_hash"}


@api.get("/auth/me")
async def me(current=Depends(auth_required)):
    return current


@api.post("/auth/logout")
async def logout(current=Depends(auth_required)):
    return {"success": True}


# ============================================================================
# Staff CRUD
# ============================================================================
@api.get("/staff")
async def list_staff(current=Depends(auth_required)):
    """Return all staff in display order (the same order the rota editor
    renders rows top-to-bottom). `display_order` is seeded from the
    grizedale.json array index × 10, so manager → deputy → seniors →
    flexis → nights. Falls back to alphabetic for any docs missing the
    field (legacy)."""
    docs = await db.staff.find({}, {"_id": 0, "password_hash": 0}).to_list(1000)
    docs.sort(key=lambda s: (s.get("display_order", 9999), s.get("initials", "")))
    return docs


@api.post("/staff")
async def create_staff(payload: StaffIn, current=Depends(auth_required)):
    if await db.staff.find_one({"initials": payload.initials}):
        raise HTTPException(status_code=400, detail="Initials already exist")
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = _now()
    doc["updated_at"] = _now()
    await db.staff.insert_one(doc)
    return _strip_id(doc)


@api.get("/staff/{staff_id}")
async def get_staff(staff_id: str, current=Depends(auth_required)):
    doc = await db.staff.find_one({"id": staff_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Staff not found")
    return doc


@api.put("/staff/{staff_id}")
async def update_staff(staff_id: str, patch: StaffPatch, current=Depends(auth_required)):
    update = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    update["updated_at"] = _now()
    res = await db.staff.find_one_and_update(
        {"id": staff_id}, {"$set": update},
        return_document=True, projection={"_id": 0},
    )
    if not res:
        raise HTTPException(status_code=404, detail="Staff not found")
    return res


@api.get("/staff/{staff_id}/references")
async def staff_references(staff_id: str, current=Depends(auth_required)):
    """Return every place in the system that references this staff
    member — rules that name them, rota assignments, leave, requests,
    request-tokens. Used by the /staff delete confirm dialog to warn
    the manager BEFORE they remove someone and break configured rules.
    """
    staff = await db.staff.find_one({"id": staff_id}, {"_id": 0})
    if not staff:
        raise HTTPException(404, "Staff not found")
    initials = staff["initials"]
    # Leave / requests / tokens counts
    leave_count = await db.leave.count_documents({"staff_initials": initials})
    requests_count = await db.requests.count_documents({"staff_initials": initials})
    tokens_count = await db.request_tokens.count_documents({"staff_initials": initials, "revoked": {"$ne": True}})
    # Assignments: sum across non-archived rotas
    asg_count = 0
    async for r in db.rotas.find({}, {"_id": 0, "assignments": 1}):
        for a in (r.get("assignments") or []):
            if a.get("staff_initials") == initials and a.get("shift") not in (None, ""):
                asg_count += 1
    # Rule references
    rules_doc = await db.rules_config.find_one({}, {"_id": 0}) or {}
    rule_hits: list[dict] = []
    for rid, rule_val in (rules_doc.get("rules") or {}).items():
        if not isinstance(rule_val, dict):
            continue
        params = rule_val.get("params") or {}
        # Common shapes: staff_initials: [...], staff_initials: "X.Y.",
        # rules: [{staff_initials: [...], ...}], staff_overrides: {X.Y.: ...}
        hit = False
        def _touch(obj):
            nonlocal hit
            if isinstance(obj, str):
                if obj == initials:
                    hit = True
            elif isinstance(obj, list):
                for o in obj:
                    _touch(o)
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    if k == initials:
                        hit = True
                    _touch(v)
        _touch(params)
        if hit:
            rule_hits.append({"rule_id": rid, "mode": rule_val.get("mode", "soft")})
    return {
        "staff_initials": initials,
        "full_name": staff.get("full_name"),
        "leave_count": leave_count,
        "requests_count": requests_count,
        "active_tokens_count": tokens_count,
        "assignments_count": asg_count,
        "rule_references": rule_hits,
    }


@api.delete("/staff/{staff_id}")
async def delete_staff(staff_id: str, current=Depends(auth_required)):
    res = await db.staff.delete_one({"id": staff_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Staff not found")
    return {"success": True}


# ============================================================================
# Service users CRUD
# ============================================================================
@api.get("/service-users")
async def list_service_users(current=Depends(auth_required)):
    return await db.service_users.find({}, {"_id": 0}).to_list(1000)


@api.post("/service-users")
async def create_service_user(payload: ServiceUserIn, current=Depends(auth_required)):
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = _now()
    doc["updated_at"] = _now()
    await db.service_users.insert_one(doc)
    return _strip_id(doc)


@api.get("/service-users/{su_id}")
async def get_service_user(su_id: str, current=Depends(auth_required)):
    doc = await db.service_users.find_one({"id": su_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Service user not found")
    return doc


@api.put("/service-users/{su_id}")
async def update_service_user(su_id: str, patch: ServiceUserPatch, current=Depends(auth_required)):
    update = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    update["updated_at"] = _now()
    res = await db.service_users.find_one_and_update(
        {"id": su_id}, {"$set": update},
        return_document=True, projection={"_id": 0},
    )
    if not res:
        raise HTTPException(status_code=404, detail="Service user not found")
    return res


@api.delete("/service-users/{su_id}")
async def delete_service_user(su_id: str, current=Depends(auth_required)):
    res = await db.service_users.delete_one({"id": su_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Service user not found")
    return {"success": True}


# ============================================================================
# Rules + Settings
# ============================================================================
@api.get("/rules")
async def get_rules(current=Depends(auth_required)):
    doc = await db.rules_config.find_one({}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rules config not initialised")
    return doc


@api.put("/rules")
async def update_rules(payload: dict[str, Any], current=Depends(auth_required)):
    if "rules" not in payload:
        raise HTTPException(status_code=400, detail="Body must include 'rules'")
    doc = await db.rules_config.find_one_and_update(
        {}, {"$set": {"rules": payload["rules"], "updated_at": _now()}},
        return_document=True, projection={"_id": 0}, upsert=True,
    )
    return doc


@api.post("/rules/reset")
async def reset_rules(current=Depends(auth_required)):
    """Reset rules_config to the seed defaults from rule_definitions.py.

    Useful when the manager has misconfigured rule rows and wants to start
    over without touching anything else (staff, leave, rotas).
    """
    from solver.rule_definitions import default_rules_config
    fresh = default_rules_config()
    doc = await db.rules_config.find_one_and_update(
        {}, {"$set": {"rules": fresh, "updated_at": _now()}},
        return_document=True, projection={"_id": 0}, upsert=True,
    )
    return doc


@api.get("/settings")
async def get_settings(current=Depends(auth_required)):
    doc = await db.settings.find_one({}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Settings not initialised")
    return doc


@api.put("/settings")
async def update_settings(payload: dict[str, Any], current=Depends(auth_required)):
    payload = dict(payload)
    payload.pop("_id", None)
    payload["updated_at"] = _now()
    doc = await db.settings.find_one_and_update(
        {}, {"$set": payload},
        return_document=True, projection={"_id": 0}, upsert=True,
    )
    return doc


# ============================================================================
# Admins
# ============================================================================
@api.get("/admins")
async def list_admins(current=Depends(auth_required)):
    return await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(1000)


@api.post("/admins")
async def create_admin(payload: RegisterIn, current=Depends(auth_required)):
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {
        "id": new_user_id(), "email": email, "name": payload.name,
        "role": payload.role or "admin",
        "password_hash": hash_password(payload.password),
        "created_at": _now(), "updated_at": _now(),
    }
    await db.users.insert_one(doc)
    safe = {k: v for k, v in doc.items() if k != "password_hash"}
    safe.pop("_id", None)
    return safe


@api.delete("/admins/{user_id}")
async def delete_admin(user_id: str, current=Depends(auth_required)):
    if user_id == current["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    res = await db.users.delete_one({"id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Admin not found")
    return {"success": True}


# ============================================================================
# Solver
# ============================================================================
@api.get("/solver/seed")
async def get_solver_seed(current=Depends(auth_required)):
    return await build_solver_payload(db)


@api.post("/solver/generate")
async def post_solver_generate(payload: dict[str, Any] | None = None, current=Depends(auth_required)):
    if not payload or not payload.get("staff"):
        payload = await build_solver_payload(db, override_start_date=(payload or {}).get("rota_start_date"))
    if "staff" not in payload or "rota_start_date" not in payload:
        raise HTTPException(status_code=400, detail="payload must include 'staff' and 'rota_start_date'")
    time_limit = int(payload.get("solver_time_limit_s", 10))
    result = solve_rota(payload, time_limit_s=time_limit)
    status_code = 200 if result.get("success") else 422
    return JSONResponse(status_code=status_code, content=result)


# ============================================================================
# Rotas (Phase 2)
# ============================================================================
async def _load_rota(rota_id: str) -> dict:
    doc = await db.rotas.find_one({"id": rota_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Rota not found")
    return doc


async def _validate_rota_doc(rota: dict) -> dict:
    """Run validator against a rota and return the report."""
    staff = await db.staff.find({}, {"_id": 0}).to_list(1000)
    rules = (await db.rules_config.find_one({}, {"_id": 0})) or {}
    rule_modes = rules.get("rules") or {}
    violations = validate_rota(rota, staff, rule_modes)
    return {"violations": violations, "summary": summarise_violations(violations)}


@api.get("/rotas")
async def list_rotas(current=Depends(auth_required)):
    docs = await db.rotas.find(
        {}, {"_id": 0, "assignments": 0}
    ).sort("start_date", -1).to_list(500)
    return docs


@api.get("/rotas/{rota_id}")
async def get_rota(rota_id: str, current=Depends(auth_required)):
    rota = await _load_rota(rota_id)
    rota["validation_report"] = await _validate_rota_doc(rota)
    return rota


@api.post("/rotas")
async def create_rota(payload: RotaCreate, current=Depends(auth_required)):
    rota = {
        "id": str(uuid.uuid4()),
        "start_date": payload.start_date,
        "weeks": payload.weeks,
        "title": payload.title or f"Rota {payload.start_date}",
        "assignments": [],
        "on_call": [],
        "status": "draft",
        "created_at": _now(),
        "updated_at": _now(),
        "created_by": current.get("email"),
    }
    await db.rotas.insert_one(rota)
    return _strip_id(rota)


@api.put("/rotas/{rota_id}")
async def update_rota(rota_id: str, payload: dict[str, Any], current=Depends(auth_required)):
    payload = dict(payload)
    payload.pop("_id", None)
    payload.pop("id", None)
    payload["updated_at"] = _now()
    res = await db.rotas.find_one_and_update(
        {"id": rota_id}, {"$set": payload},
        return_document=True, projection={"_id": 0},
    )
    if not res:
        raise HTTPException(status_code=404, detail="Rota not found")
    res["validation_report"] = await _validate_rota_doc(res)
    return res


@api.delete("/rotas/{rota_id}")
async def delete_rota(rota_id: str, current=Depends(auth_required)):
    res = await db.rotas.delete_one({"id": rota_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Rota not found")
    return {"success": True}


@api.patch("/rotas/{rota_id}/cell")
async def patch_cell(rota_id: str, patch: CellPatch, current=Depends(auth_required)):
    rota = await _load_rota(rota_id)
    assignments = rota.get("assignments") or []

    # Find matching cell
    found = None
    for a in assignments:
        if a["date"] == patch.date and a["staff_initials"] == patch.staff_initials:
            found = a
            break

    # Locked check — refuse any shift change while the cell remains locked.
    # The only way to edit a locked cell is to also unlock it (locked=False)
    # in the same patch. Without this, the frontend popover could change
    # the shift on a locked cell silently because patch.locked stayed true.
    if found and found.get("locked"):
        new_locked = patch.locked if patch.locked is not None else found.get("locked", False)
        if patch.shift != found.get("shift") and new_locked:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cell is locked ({patch.staff_initials} on {patch.date}). "
                    "Unlock it first or pass locked=false in the same patch to "
                    "change the shift."
                ),
            )

    new_cell = {
        "date": patch.date,
        "staff_initials": patch.staff_initials,
        "shift": patch.shift,
        "locked": patch.locked if patch.locked is not None else (found.get("locked", False) if found else False),
    }
    if patch.reason is not None:
        new_cell["reason"] = patch.reason

    if found:
        assignments = [
            new_cell if (a["date"] == patch.date and a["staff_initials"] == patch.staff_initials) else a
            for a in assignments
        ]
    else:
        assignments.append(new_cell)

    await db.rotas.update_one(
        {"id": rota_id},
        {"$set": {"assignments": assignments, "updated_at": _now()}},
    )
    rota["assignments"] = assignments
    rota["updated_at"] = _now()
    rota["validation_report"] = await _validate_rota_doc(rota)
    return {"cell": new_cell, "validation_report": rota["validation_report"]}


@api.patch("/rotas/{rota_id}/cells")
async def patch_cells_bulk(
    rota_id: str,
    patch: CellBulkPatch,
    current=Depends(auth_required),
):
    """Atomic multi-cell update with a single validation pass.

    Used by the multi-select / week-lock UI on /rotas/:id. Each update may
    contain `shift`, `locked` and/or `reason`. Omitted fields preserve the
    existing value. Locked cells are skipped unless `force=true` (used by
    the bulk "Unlock" action).
    """
    rota = await _load_rota(rota_id)
    assignments = list(rota.get("assignments") or [])
    by_key: dict[tuple[str, str], dict] = {
        (a["date"], a["staff_initials"]): a for a in assignments
    }

    applied = 0
    skipped_locked: list[dict] = []
    for upd in patch.updates:
        key = (upd.date, upd.staff_initials)
        existing = by_key.get(key)
        # Block edits to locked cells unless the caller is explicitly
        # unlocking (locked=False) or `force=True` was passed.
        if existing and existing.get("locked") and not patch.force and upd.locked is not False:
            skipped_locked.append({"date": upd.date, "staff_initials": upd.staff_initials})
            continue

        new_shift = upd.shift if upd.shift is not None else (existing or {}).get("shift", "")
        new_locked = (
            upd.locked
            if upd.locked is not None
            else (existing or {}).get("locked", False)
        )
        new_cell = {
            "date": upd.date,
            "staff_initials": upd.staff_initials,
            "shift": new_shift,
            "locked": bool(new_locked),
        }
        # Preserve existing reason unless overridden
        if upd.reason is not None:
            new_cell["reason"] = upd.reason
        elif existing and existing.get("reason"):
            new_cell["reason"] = existing["reason"]

        by_key[key] = new_cell
        applied += 1

    new_assignments = list(by_key.values())
    await db.rotas.update_one(
        {"id": rota_id},
        {"$set": {"assignments": new_assignments, "updated_at": _now()}},
    )
    rota["assignments"] = new_assignments
    rota["updated_at"] = _now()
    rota["validation_report"] = await _validate_rota_doc(rota)
    return {
        "applied": applied,
        "skipped_locked": skipped_locked,
        "validation_report": rota["validation_report"],
    }


@api.post("/rotas/{rota_id}/validate")
async def revalidate(rota_id: str, current=Depends(auth_required)):
    rota = await _load_rota(rota_id)
    return await _validate_rota_doc(rota)


@api.post("/rotas/{rota_id}/copy-from-previous")
async def copy_from_previous(rota_id: str, current=Depends(auth_required)):
    target = await _load_rota(rota_id)
    weeks = target.get("weeks", 4)
    target_start = datetime.strptime(target["start_date"], "%Y-%m-%d").date()

    # Find the most recent prior rota (older start_date than this rota)
    prior = await db.rotas.find_one(
        {"start_date": {"$lt": target["start_date"]}, "id": {"$ne": rota_id}},
        sort=[("start_date", -1)],
        projection={"_id": 0},
    )
    if not prior:
        raise HTTPException(status_code=404, detail="No prior rota to copy from")

    prior_start = datetime.strptime(prior["start_date"], "%Y-%m-%d").date()

    # Map prior assignments by (day_index 0..weeks*7-1, initials)
    prior_by_idx_init: dict[tuple[int, str], str] = {}
    for a in prior.get("assignments", []):
        a_date = datetime.strptime(a["date"], "%Y-%m-%d").date()
        idx = (a_date - prior_start).days
        if 0 <= idx < weeks * 7:
            prior_by_idx_init[(idx, a["staff_initials"])] = a["shift"]

    # Build new assignments for target rota
    new_assignments: list[dict] = []
    n_days = weeks * 7
    target_dates = [(target_start + timedelta(days=i)).isoformat() for i in range(n_days)]
    for idx, d_str in enumerate(target_dates):
        for (i_idx, init), shift in prior_by_idx_init.items():
            if i_idx == idx:
                new_assignments.append({
                    "date": d_str,
                    "staff_initials": init,
                    "shift": shift,
                    "locked": False,
                })

    # Overlay current `leave` collection entries inside the target window
    leave_docs = await db.leave.find(
        {"date": {"$gte": target_dates[0], "$lte": target_dates[-1]}},
        {"_id": 0},
    ).to_list(10000)
    leave_by_key = {(l_["date"], l_["staff_initials"]): l_["type"] for l_ in leave_docs}

    overlaid = []
    for cell in new_assignments:
        key = (cell["date"], cell["staff_initials"])
        if key in leave_by_key:
            t = leave_by_key[key]
            cell = {**cell, "shift": "AL" if t == "AL" else "TRN" if t == "TRN" else cell["shift"]}
        overlaid.append(cell)
    # Add leave cells for staff that weren't in the prior rota
    existing_keys = {(c["date"], c["staff_initials"]) for c in overlaid}
    for key, t in leave_by_key.items():
        if key not in existing_keys:
            overlaid.append({
                "date": key[0],
                "staff_initials": key[1],
                "shift": "AL" if t == "AL" else "TRN" if t == "TRN" else "OFF",
                "locked": False,
            })

    await db.rotas.update_one(
        {"id": rota_id},
        {"$set": {"assignments": overlaid, "updated_at": _now()}},
    )
    target["assignments"] = overlaid
    report = await _validate_rota_doc(target)
    return {
        "success": True,
        "copied_from": {"id": prior["id"], "start_date": prior["start_date"]},
        "assignments_count": len(overlaid),
        "leave_overlaid": len(leave_by_key),
        "validation_report": report,
    }


@api.post("/rotas/{rota_id}/generate")
async def generate_rota(rota_id: str, current=Depends(auth_required)):
    """Run the CP-SAT solver to fill the rota. Preserves locked cells, AL,
    and TRN. Accepted non-OFF requests become soft preferences."""
    rota = await _load_rota(rota_id)
    weeks = int(rota.get("weeks", 4))
    start_date = rota["start_date"]
    end_dt = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=weeks * 7 - 1)
    end_date = end_dt.strftime("%Y-%m-%d")

    # 1. Build base solver payload from Mongo state
    payload = await build_solver_payload(db, override_start_date=start_date)
    payload["weeks"] = weeks

    # 2. Locked cells from rota.assignments where locked=True
    locked_cells = [
        {"staff_initials": a["staff_initials"], "date": a["date"], "shift": a["shift"]}
        for a in (rota.get("assignments") or [])
        if a.get("locked") and a.get("shift")
    ]
    payload["locked_cells"] = locked_cells

    # 2a. PRE-VALIDATE locked cells before calling the solver. The solver
    # would otherwise return a generic INFEASIBLE that doesn't pinpoint
    # *which* lock is at fault. Catching capability mismatches here gives
    # the manager a clear, immediately-fixable error.
    staff_by_init = {s["initials"]: s for s in payload["staff"]}
    pre_check_errors: list[dict] = []
    for lock in locked_cells:
        s_doc = staff_by_init.get(lock["staff_initials"])
        if not s_doc:
            pre_check_errors.append({
                "date": lock["date"],
                "day_of_week": _dow_short(lock["date"]),
                "problems": [f"Locked cell references unknown / inactive staff '{lock['staff_initials']}'"],
            })
            continue
        sh = lock["shift"]
        if sh in ("D",) and not s_doc.get("can_do_days", True):
            pre_check_errors.append({
                "date": lock["date"],
                "day_of_week": _dow_short(lock["date"]),
                "problems": [f"{lock['staff_initials']} is locked to D but `can_do_days` is False"],
            })
        elif sh in ("D*",) and (not s_doc.get("can_do_days", True) or not s_doc.get("can_do_sleepover", False)):
            pre_check_errors.append({
                "date": lock["date"],
                "day_of_week": _dow_short(lock["date"]),
                "problems": [f"{lock['staff_initials']} is locked to D* but is not flagged for both day + sleepover"],
            })
        elif sh == "N" and not s_doc.get("can_do_nights", False):
            pre_check_errors.append({
                "date": lock["date"],
                "day_of_week": _dow_short(lock["date"]),
                "problems": [f"{lock['staff_initials']} is locked to N but `can_do_nights` is False"],
            })
        elif sh == "*" and not s_doc.get("can_do_sleepover", False):
            pre_check_errors.append({
                "date": lock["date"],
                "day_of_week": _dow_short(lock["date"]),
                "problems": [f"{lock['staff_initials']} is locked to * but `can_do_sleepover` is False"],
            })

    # 2b. Detect conflict between a lock and a leave row (same staff+date).
    # If the user locked a working shift on a date the staff has AL/TRN,
    # the solver would treat the lock as winner but the manager probably
    # didn't intend that — surface it as a warning.
    leave_keys = {(l_["staff_initials"], l_["date"]): l_["type"]
                  for l_ in await db.leave.find(
                      {"date": {"$gte": start_date, "$lte": end_date}}, {"_id": 0}
                  ).to_list(10000)
                  if l_.get("type") in {"AL", "TRN"}}
    for lock in locked_cells:
        leave_type = leave_keys.get((lock["staff_initials"], lock["date"]))
        if leave_type and lock["shift"] not in {"AL", "TRN", "OFF"}:
            pre_check_errors.append({
                "date": lock["date"],
                "day_of_week": _dow_short(lock["date"]),
                "problems": [
                    f"{lock['staff_initials']} is locked to {lock['shift']} on {lock['date']} "
                    f"but has {leave_type} on the same date — remove either the lock or the leave"
                ],
            })

    if pre_check_errors:
        # Group by date (one entry per conflicting date)
        by_date: dict[str, dict] = {}
        for e in pre_check_errors:
            d = e["date"]
            if d not in by_date:
                by_date[d] = {"date": d, "day_of_week": e["day_of_week"], "problems": []}
            by_date[d]["problems"].extend(e["problems"])
        return JSONResponse(status_code=422, content={
            "success": False,
            "reason": (
                f"Cannot generate — {len(pre_check_errors)} locked cell"
                f"{'' if len(pre_check_errors) == 1 else 's'} conflict with hard rules "
                f"(staff capabilities or existing leave). Fix the lock(s) and try again."
            ),
            "blocking_constraints": list(by_date.values()),
            "solver_status": "PRE_CHECK_FAILED",
            "solve_time_ms": 0,
        })

    # 3. AL / TRN cells from `leave` collection within the date window
    leave_docs = await db.leave.find(
        {"date": {"$gte": start_date, "$lte": end_date}}, {"_id": 0}
    ).to_list(10000)
    payload["leave"] = [
        {
            "staff_initials": l_["staff_initials"],
            "date": l_["date"],
            "type": l_["type"] if l_["type"] in {"AL", "TRN"} else "AL",
        }
        for l_ in leave_docs
        if l_.get("type") in {"AL", "TRN", "OFF_REQ"}
    ]

    # 4. Accepted non-OFF requests → soft preferences
    accepted_reqs = await db.requests.find(
        {
            "status": "accepted",
            "date": {"$gte": start_date, "$lte": end_date},
            "shift_preference": {"$nin": ["OFF"]},
        },
        {"_id": 0},
    ).to_list(10000)
    payload["accepted_requests"] = accepted_reqs

    # 5. Solve. Wrap in try/except so a solver-internal failure surfaces
    # as a clean 422 with a useful message instead of a 500.
    time_limit = int(payload.get("solver_time_limit_s", 12))
    try:
        result = solve_rota(payload, time_limit_s=time_limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Solver internal error during /generate (rota=%s)", rota_id)
        return JSONResponse(status_code=422, content={
            "success": False,
            "reason": f"Solver crashed: {type(exc).__name__}: {exc}",
            "blocking_constraints": [],
            "solver_status": "INTERNAL_ERROR",
            "solve_time_ms": 0,
        })

    if not result.get("success"):
        # Augment the reason when blocking_constraints is empty so the
        # frontend always has *something* useful to show.
        reason = result.get("reason") or (
            f"Solver returned {result.get('solver_status', 'no solution')} but "
            f"could not pinpoint specific blockers. Try unlocking some cells "
            f"and re-generating."
        )
        return JSONResponse(status_code=422, content={
            "success": False,
            "reason": reason,
            "blocking_constraints": result.get("blocking_constraints", []),
            "solver_status": result.get("solver_status"),
            "solve_time_ms": result.get("solve_time_ms"),
        })

    # 6. Merge solver output into rota.assignments, preserving locked cells
    locked_keys = {(a["date"], a["staff_initials"]) for a in (rota.get("assignments") or []) if a.get("locked")}
    existing_by_key = {(a["date"], a["staff_initials"]): a for a in (rota.get("assignments") or [])}
    new_assignments = []
    for day in result["rota"]:
        for a in day["assignments"]:
            key = (day["date"], a["staff_initials"])
            if key in locked_keys:
                # Preserve the locked cell exactly (including any reason/etc.)
                new_assignments.append(existing_by_key[key])
            else:
                new_assignments.append({
                    "date": day["date"],
                    "staff_initials": a["staff_initials"],
                    "shift": a["shift"],
                    "locked": False,
                })

    await db.rotas.update_one(
        {"id": rota_id},
        {"$set": {"assignments": new_assignments, "updated_at": _now()}},
    )
    rota["assignments"] = new_assignments
    report = await _validate_rota_doc(rota)
    return {
        "success": True,
        "assignments_count": len(new_assignments),
        "soft_violations_score": result.get("soft_violations_score"),
        "solve_time_ms": result.get("solve_time_ms"),
        "solver_status": result.get("solver_status"),
        "validation_report": report,
        "warnings": result.get("warnings", []),
        "locked_preserved": len(locked_keys),
        "leave_preserved": len(payload["leave"]),
    }


# ============================================================================
# Phase 4: Exports (PDF + Excel)
# ============================================================================
@api.get("/rotas/{rota_id}/export.pdf")
async def export_rota_pdf(
    rota_id: str,
    theme: str = Query(default="paper", regex="^(paper|modern)$"),
    current=Depends(auth_required),
):
    from exports.pdf_rota import render_rota_pdf
    rota = await _load_rota(rota_id)
    staff = await db.staff.find({"active": True}, {"_id": 0}).to_list(100)
    # Match the on-screen rota row order (display_order then initials).
    staff.sort(key=lambda s: (s.get("display_order", 9999), s.get("initials", "")))
    settings = await db.settings.find_one({}, {"_id": 0}) or {}
    home_name = settings.get("home_name", "Grizedale")
    pdf_bytes = render_rota_pdf(rota, staff, home_name=home_name, theme=theme)
    fname = f"{home_name.lower()}-rota-{rota['start_date']}-{theme}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.get("/rotas/{rota_id}/export.xlsx")
async def export_rota_xlsx(
    rota_id: str,
    theme: str = Query(default="paper", regex="^(paper|modern)$"),
    current=Depends(auth_required),
):
    from exports.excel_rota import render_rota_xlsx
    rota = await _load_rota(rota_id)
    staff = await db.staff.find({"active": True}, {"_id": 0}).to_list(100)
    staff.sort(key=lambda s: (s.get("display_order", 9999), s.get("initials", "")))
    settings = await db.settings.find_one({}, {"_id": 0}) or {}
    home_name = settings.get("home_name", "Grizedale")
    xlsx_bytes = render_rota_xlsx(rota, staff, home_name=home_name, theme=theme)
    fname = f"{home_name.lower()}-rota-{rota['start_date']}-{theme}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.get("/holidays/export.pdf")
async def export_holiday_pdf(
    year: int = Query(default=2026),
    theme: str = Query(default="paper", regex="^(paper|modern)$"),
    current=Depends(auth_required),
):
    from exports.pdf_holiday import render_holiday_pdf
    leave_rows = await db.leave.find(
        {"date": {"$gte": f"{year}-01-01", "$lte": f"{year}-12-31"}},
        {"_id": 0},
    ).to_list(10000)
    settings = await db.settings.find_one({}, {"_id": 0}) or {}
    home_name = settings.get("home_name", "Grizedale")
    public_holidays = settings.get("public_holidays") or []
    pdf_bytes = render_holiday_pdf(year, leave_rows, public_holidays, home_name=home_name, theme=theme)
    fname = f"{home_name.lower()}-holiday-sheet-{year}-{theme}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ============================================================================
# Leave (Phase 2)
# ============================================================================
@api.get("/leave")
async def list_leave(
    current=Depends(auth_required),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    staff: str | None = Query(default=None),
):
    q: dict[str, Any] = {}
    if from_ or to:
        date_q: dict[str, Any] = {}
        if from_:
            date_q["$gte"] = from_
        if to:
            date_q["$lte"] = to
        q["date"] = date_q
    if staff:
        q["staff_initials"] = staff
    return await db.leave.find(q, {"_id": 0}).sort("date", 1).to_list(10000)


@api.post("/leave")
async def create_leave(payload: LeaveBulkIn, current=Depends(auth_required)):
    # max_one_per_role_on_al guard — when creating AL, refuse if another
    # staff sharing the same role is already on AL the same date.
    if payload.type == "AL":
        rules_doc = await db.rules_config.find_one({}, {"_id": 0}) or {}
        rule_mode = ((rules_doc.get("rules") or {}).get("max_one_per_role_on_al") or {}).get("mode", "hard")
        if rule_mode == "hard":
            me = await db.staff.find_one(
                {"initials": payload.staff_initials},
                {"_id": 0, "role": 1},
            )
            my_role = (me or {}).get("role")
            if my_role:
                same_role = await db.staff.find(
                    {"role": my_role, "initials": {"$ne": payload.staff_initials}, "active": True},
                    {"_id": 0, "initials": 1},
                ).to_list(100)
                role_mates = [s["initials"] for s in same_role]
                if role_mates:
                    for d in payload.dates:
                        conflict = await db.leave.find_one(
                            {
                                "staff_initials": {"$in": role_mates},
                                "date": d,
                                "type": "AL",
                            },
                            {"_id": 0, "staff_initials": 1, "date": 1},
                        )
                        if conflict:
                            raise HTTPException(
                                status_code=422,
                                detail=(
                                    f"Cannot add AL — {conflict['staff_initials']} ({my_role}) "
                                    f"is already on AL on {d}. Only one per role per day."
                                ),
                            )

    created: list[dict] = []
    for d in payload.dates:
        doc = {
            "id": str(uuid.uuid4()),
            "staff_initials": payload.staff_initials,
            "date": d,
            "type": payload.type,
            "notes": payload.notes,
            "created_at": _now(),
        }
        try:
            await db.leave.insert_one(doc)
            created.append(_strip_id(doc))
            logger.info("LEAVE_INSERT staff=%s date=%s type=%s by=%s",
                        payload.staff_initials, d, payload.type,
                        (current or {}).get("email", "?"))
        except Exception:
            # Duplicate (staff_initials, date) — update type instead
            await db.leave.update_one(
                {"staff_initials": payload.staff_initials, "date": d},
                {"$set": {"type": payload.type, "notes": payload.notes}},
            )
            existing = await db.leave.find_one(
                {"staff_initials": payload.staff_initials, "date": d}, {"_id": 0}
            )
            if existing:
                created.append(existing)
            logger.info("LEAVE_UPDATE staff=%s date=%s new_type=%s by=%s",
                        payload.staff_initials, d, payload.type,
                        (current or {}).get("email", "?"))
    return created


@api.delete("/leave/{leave_id}")
async def delete_leave(leave_id: str, current=Depends(auth_required)):
    target = await db.leave.find_one({"id": leave_id}, {"_id": 0})
    res = await db.leave.delete_one({"id": leave_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Leave not found")
    logger.info("LEAVE_DELETE id=%s staff=%s date=%s type=%s by=%s",
                leave_id,
                (target or {}).get("staff_initials"),
                (target or {}).get("date"),
                (target or {}).get("type"),
                (current or {}).get("email", "?"))
    return {"success": True}


# ============================================================================
# Requests (Phase 2)
# ============================================================================
@api.get("/requests")
async def list_requests(current=Depends(auth_required), status: str | None = None):
    q = {"status": status} if status else {}
    rows = await db.requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(10000)
    # Decorate each pending row with a `conflicts` block so the manager
    # can see clashes at a glance (other staff already on leave same day
    # / role-collision for OFF / AL requests).
    for r in rows:
        if r.get("status") != "pending":
            r["conflicts"] = None
            continue
        try:
            r["conflicts"] = await _check_leave_slot(
                r.get("staff_initials", ""),
                r.get("date", ""),
                r.get("shift_preference", "") or "",
            )
        except Exception:
            r["conflicts"] = None
    return rows


@api.post("/requests")
async def create_request(payload: RequestIn, current=Depends(auth_required)):
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["status"] = "pending"
    doc["resolution_note"] = None
    doc["resolved_at"] = None
    doc["created_at"] = _now()
    await db.requests.insert_one(doc)
    return _strip_id(doc)


async def _log_audit(
    actor_email: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Insert a row into the `audit_log` collection. Non-fatal — failures
    are logged but never raise so the main request flow continues.

    Schema: {id, actor_email, action, details, timestamp}
    """
    try:
        await db.audit_log.insert_one({
            "id": str(uuid.uuid4()),
            "actor_email": actor_email or "unknown",
            "action": action,
            "details": details or {},
            "timestamp": _now(),
        })
    except Exception as exc:
        logger.warning("audit_log insert failed (%s): %s", action, exc)


async def _resolve_request(
    req: dict,
    status: str,
    resolution_note: str | None,
    *,
    actor_email: str = "",
    override_conflict: bool = False,
    override_reason: str | None = None,
) -> dict:
    update = {
        "status": status,
        "resolution_note": resolution_note,
        "resolved_at": _now(),
    }
    if override_conflict:
        update["override_conflict"] = True
        update["override_reason"] = override_reason or ""
    res = await db.requests.find_one_and_update(
        {"id": req["id"]}, {"$set": update},
        return_document=True, projection={"_id": 0},
    )
    # Audit the override when one was recorded.
    if override_conflict and status == "accepted":
        await _log_audit(actor_email, "override_conflict", {
            "request_id": req.get("id"),
            "staff_initials": req.get("staff_initials"),
            "date": req.get("date"),
            "shift_preference": req.get("shift_preference"),
            "reason": override_reason or "",
        })
    # If accepted + OFF preference, upsert a leave row of type OFF_REQ
    # (overwrites any existing AL/TRN entry for the same staff+date).
    if (
        status == "accepted"
        and req.get("shift_preference") == "OFF"
    ):
        try:
            notes = f"From request: {req.get('notes', '')}".rstrip(": ")
            await db.leave.update_one(
                {"staff_initials": req["staff_initials"], "date": req["date"]},
                {
                    "$set": {
                        "type": "OFF_REQ",
                        "notes": notes,
                        "updated_at": _now(),
                    },
                    "$setOnInsert": {
                        "id": str(uuid.uuid4()),
                        "staff_initials": req["staff_initials"],
                        "date": req["date"],
                        "created_at": _now(),
                    },
                },
                upsert=True,
            )
        except Exception as exc:
            logger.warning("Failed to upsert OFF_REQ leave for %s on %s: %s",
                           req.get("staff_initials"), req.get("date"), exc)
    return res


@api.patch("/requests/{req_id}")
async def patch_request(req_id: str, patch: RequestPatch, current=Depends(auth_required)):
    existing = await db.requests.find_one({"id": req_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Request not found")
    if patch.status:
        # Accept path — enforce max_one_per_role_on_al unless the manager
        # has explicitly ticked `override_conflict` + supplied a reason.
        if patch.status == "accepted":
            conflict = await _check_leave_slot(
                existing.get("staff_initials", ""),
                existing.get("date", ""),
                existing.get("shift_preference", "") or "",
            )
            if not conflict.get("slot_open"):
                if not patch.override_conflict:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "conflict",
                            "reason": conflict.get("reason") or "Slot taken",
                            "existing_leave": conflict.get("existing_leave") or [],
                        },
                    )
                if not (patch.override_reason and patch.override_reason.strip()):
                    raise HTTPException(
                        status_code=422,
                        detail="override_reason is required when override_conflict=true",
                    )
        return await _resolve_request(
            existing, patch.status, patch.resolution_note,
            actor_email=(current or {}).get("email", ""),
            override_conflict=patch.override_conflict,
            override_reason=patch.override_reason,
        )
    update = {k: v for k, v in patch.model_dump().items() if v is not None}
    res = await db.requests.find_one_and_update(
        {"id": req_id}, {"$set": update},
        return_document=True, projection={"_id": 0},
    )
    return res


@api.post("/requests/bulk")
async def bulk_patch_requests(payload: RequestBulkPatch, current=Depends(auth_required)):
    """Bulk-resolve requests.

    When `status=accepted`, every candidate is pre-checked against
    `max_one_per_role_on_al`. Conflicting requests are SKIPPED unless
    the caller supplies `override_conflict=true` + `override_reason`;
    in that case each conflict is resolved with an override log entry.

    Response shape:
        {
            "updated": [...requests...],
            "leave_created": int,
            "skipped_conflicts": [
                {"request_id": ..., "reason": ..., "existing_leave": [...]},
                ...
            ],
        }
    """
    updated: list[dict] = []
    skipped_conflicts: list[dict] = []
    leave_created = 0
    actor_email = (current or {}).get("email", "")

    if payload.status == "accepted" and payload.override_conflict and not (
        payload.override_reason and payload.override_reason.strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="override_reason is required when override_conflict=true",
        )

    for rid in payload.ids:
        existing = await db.requests.find_one({"id": rid}, {"_id": 0})
        if not existing:
            continue

        # On accept, check for conflicts. If override_conflict is false
        # and a conflict exists, skip that row (manager will re-submit
        # with override). If override_conflict=true, proceed with the
        # override logged to audit_log.
        if payload.status == "accepted":
            conflict = await _check_leave_slot(
                existing.get("staff_initials", ""),
                existing.get("date", ""),
                existing.get("shift_preference", "") or "",
            )
            if not conflict.get("slot_open") and not payload.override_conflict:
                skipped_conflicts.append({
                    "request_id": rid,
                    "staff_initials": existing.get("staff_initials"),
                    "date": existing.get("date"),
                    "reason": conflict.get("reason") or "Slot taken",
                    "existing_leave": conflict.get("existing_leave") or [],
                })
                continue

            override_for_this = payload.override_conflict and not conflict.get("slot_open")
        else:
            override_for_this = False

        before_leave_count = await db.leave.count_documents({})
        result = await _resolve_request(
            existing, payload.status, payload.resolution_note,
            actor_email=actor_email,
            override_conflict=override_for_this,
            override_reason=payload.override_reason,
        )
        after_leave_count = await db.leave.count_documents({})
        if after_leave_count > before_leave_count:
            leave_created += 1
        if result:
            updated.append(result)
    return {
        "updated": updated,
        "leave_created": leave_created,
        "skipped_conflicts": skipped_conflicts,
    }


@api.get("/audit-log")
async def list_audit_log(
    current=Depends(auth_required),
    action: str | None = None,
    limit: int = 200,
):
    """Return the most recent audit entries (descending timestamp)."""
    q = {"action": action} if action else {}
    rows = await (
        db.audit_log.find(q, {"_id": 0})
        .sort("timestamp", -1)
        .to_list(max(1, min(limit, 1000)))
    )
    return rows


# ============================================================================
# Request tokens (Phase 2)
# ============================================================================
async def _shorten_url(long_url: str) -> tuple[str | None, str]:
    """Shorten a URL using a chain of free no-auth shorteners that all
    redirect DIRECTLY to the target (no preview / confirmation page).

    Provider order (most-direct first):
        1. is.gd   — `https://is.gd/create.php?format=simple&url=<url>`
                     6-7 char tokens, no preview page, very stable.
        2. da.gd   — `https://da.gd/s?url=<url>`
                     5-6 char tokens, also direct.
        3. (fallback) — return None so caller uses the long URL.

    Returns `(short_url, provider)`. provider is one of
    {"is.gd", "da.gd", "direct"}. Network failures are logged at WARNING
    and the chain falls through silently — generating a token never
    blocks on a flaky external API.
    """
    import httpx

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        # 1) is.gd
        try:
            resp = await client.get(
                "https://is.gd/create.php",
                params={"format": "simple", "url": long_url},
            )
            if resp.status_code == 200:
                short = (resp.text or "").strip()
                if short.startswith("http") and "Error" not in short:
                    return short, "is.gd"
                logger.warning("is.gd returned non-URL payload: %r", short[:100])
            else:
                logger.warning("is.gd non-200 (%d) for %s", resp.status_code, long_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("is.gd call failed: %s", exc)

        # 2) da.gd
        try:
            resp = await client.get(
                "https://da.gd/s",
                params={"url": long_url},
            )
            if resp.status_code == 200:
                short = (resp.text or "").strip()
                if short.startswith("http"):
                    return short, "da.gd"
                logger.warning("da.gd returned non-URL payload: %r", short[:100])
            else:
                logger.warning("da.gd non-200 (%d) for %s", resp.status_code, long_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("da.gd call failed: %s", exc)

    # All providers failed — caller will fall back to the long URL.
    return None, "direct"


def _public_base_url(request: Request) -> str:
    """Return the public origin (scheme://host) the request came in on, e.g.
    'https://care-rota-engine.preview.emergentagent.com'. Honours the
    `X-Forwarded-Host` / `X-Forwarded-Proto` headers set by the ingress
    so internal pod-localhost requests don't accidentally produce a
    private URL. Manager can override via BASE_APP_URL env var if needed.
    """
    env_url = os.environ.get("BASE_APP_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    return f"{fwd_proto}://{fwd_host}"


@api.get("/request-tokens")
async def list_tokens(current=Depends(auth_required)):
    return await db.request_tokens.find({"revoked": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@api.post("/request-tokens")
async def create_token(payload: TokenCreate, request: Request, current=Depends(auth_required)):
    """Generate a SHORT request-link token for a staff member.

    The token is a 6-char base62 string (e.g. `x7kbP9`) so the URL stays
    pasteable in a text message. We retry on the (very unlikely) collision.
    The full URL is then shortened (is.gd → da.gd → direct fallback) to
    produce an even shorter link the manager can text/email to the
    staff member. is.gd / da.gd both redirect DIRECTLY to the target
    with no preview/confirmation page (TinyURL was abandoned because it
    sometimes shows a "suspicious URL" warning before forwarding). If
    both shorteners fail we fall back to the long URL — token creation
    never blocks on the external API.

    Custom-hostname note: the public URL is served from the deployment
    host (e.g. `<app>.preview.emergentagent.com`). Set BASE_APP_URL env
    var to override.
    """
    import string
    alphabet = string.ascii_letters + string.digits  # 62 chars
    for _ in range(8):
        token = "".join(secrets.choice(alphabet) for _ in range(6))
        existing = await db.request_tokens.find_one({"token": token}, {"_id": 0, "id": 1})
        if not existing:
            break
    else:
        token = secrets.token_urlsafe(8)

    base = _public_base_url(request)
    long_url = f"{base}/r/{token}"
    short_url, short_provider = await _shorten_url(long_url)

    doc = {
        "id": str(uuid.uuid4()),
        "token": token,
        "staff_initials": payload.staff_initials,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)).isoformat(),
        "revoked": False,
        "long_url": long_url,
        "short_url": short_url,
        "short_url_provider": short_provider,
        "created_at": _now(),
    }
    await db.request_tokens.insert_one(doc)
    return {**_strip_id(doc), "url": f"/r/{token}"}


@api.post("/request-tokens/{token_id}/revoke")
async def revoke_token(token_id: str, current=Depends(auth_required)):
    res = await db.request_tokens.update_one(
        {"id": token_id},
        {"$set": {"revoked": True}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"success": True}


# ============================================================================
# Public request link (NO AUTH)
# ============================================================================
async def _resolve_token(token: str) -> dict:
    doc = await db.request_tokens.find_one({"token": token}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Link not found")
    if doc.get("revoked"):
        raise HTTPException(status_code=410, detail="This link has been revoked")
    expires = datetime.fromisoformat(doc["expires_at"])
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This link has expired")
    return doc


@api.get("/public/request-link/{token}")
async def public_get(token: str):
    doc = await _resolve_token(token)
    staff = await db.staff.find_one({"initials": doc["staff_initials"]}, {"_id": 0, "password_hash": 0})
    # The request window now spans from today up to Dec 31 of the
    # following year — gives staff a long runway to plan holidays per
    # user request (prev behaviour was the current 4-week rota only).
    today = datetime.now(timezone.utc).date()
    end_of_next_year = date(today.year + 1, 12, 31)
    return {
        "staff_initials": doc["staff_initials"],
        "name": staff.get("full_name") if staff else doc["staff_initials"],
        "role": (staff or {}).get("role", ""),
        "valid_until": doc["expires_at"],
        "window": {"from": today.isoformat(), "to": end_of_next_year.isoformat()},
        # Kept for backward compatibility with older public pages.
        "current_rota_window": {"from": today.isoformat(), "to": end_of_next_year.isoformat()},
    }


async def _check_leave_slot(staff_initials: str, date_str: str, preference: str) -> dict:
    """Inspect a candidate (staff, date, preference) for an off-type
    request and return rich slot-availability info.

    Response shape (Phase 4):
        {
          "slot_status":     "open" | "role_conflict" | "hard_limit",
          "existing_leave":  [{"staff_initials","role","type"}, ...],   # any leave on date
          "would_break_rules": ["max_one_per_role_on_al", ...],
          # Backwards-compat fields used by the manager-side conflicts column:
          "slot_open":       bool,
          "reason":          str|None,
        }

    Rules honoured:
      - `max_one_per_role_on_al`: a role can only have ONE staff on AL
        / OFF on the same date. (Manager / admin-only is exempt.)
      - Existing leave for the same staff / same date is treated as a
        hard self-conflict.
      - All OTHER existing leave on the same date is surfaced as info
        (amber chip on the staff page) but does NOT block submission.
    """
    preference = (preference or "").upper()
    is_off_type = preference in {"OFF", "AL"}

    staff = await db.staff.find_one({"initials": staff_initials}, {"_id": 0})
    if not staff:
        return {
            "slot_status": "hard_limit",
            "slot_open": False,
            "reason": "Staff not found",
            "existing_leave": [],
            "would_break_rules": [],
        }

    # Pull every leave row for that date (regardless of role) so the
    # public page can flag who is off — even when there's no actual
    # rule conflict, the staff member should still see who else is off.
    raw_leave = await db.leave.find(
        {"date": date_str, "type": {"$in": ["AL", "OFF_REQ", "TRN"]}},
        {"_id": 0},
    ).to_list(50)

    # Hydrate each leave row with the staff role for nicer UX.
    role_by_initials: dict[str, str] = {}
    if raw_leave:
        same_dates_inits = list({e["staff_initials"] for e in raw_leave})
        async for s in db.staff.find(
            {"initials": {"$in": same_dates_inits}}, {"_id": 0, "initials": 1, "role": 1}
        ):
            role_by_initials[s["initials"]] = s.get("role", "")
    existing_leave = [
        {
            "staff_initials": e["staff_initials"],
            "role": role_by_initials.get(e["staff_initials"], ""),
            "type": e["type"],
        }
        for e in raw_leave
    ]

    # Working-shift preferences (WANT_D / WANT_N etc.) never trigger a
    # hard-limit; just return the existing-leave list as INFO.
    if not is_off_type:
        return {
            "slot_status": "open",
            "slot_open": True,
            "reason": None,
            "existing_leave": existing_leave,
            "would_break_rules": [],
        }

    # Self already on leave on that date → hard self-conflict.
    if any(e["staff_initials"] == staff_initials for e in existing_leave):
        return {
            "slot_status": "hard_limit",
            "slot_open": False,
            "reason": f"{staff_initials} is already on leave on {date_str}.",
            "existing_leave": existing_leave,
            "would_break_rules": ["self_already_off"],
        }

    # Role-collision check: max-one-per-role-on-AL.
    staff_role = (staff.get("role") or "").strip()
    is_admin = bool(staff.get("is_admin_only") or staff.get("is_manager"))
    if is_admin or not staff_role:
        # Manager / role-less staff always pass the role-collision rule.
        return {
            "slot_status": "open",
            "slot_open": True,
            "reason": None,
            "existing_leave": existing_leave,
            "would_break_rules": [],
        }

    role_lower = staff_role.lower()
    # Same-role colleagues already off? Surface red banner + reason.
    clashing = [
        e for e in existing_leave
        if e["staff_initials"] != staff_initials
        and (e.get("role") or "").strip().lower() == role_lower
    ]
    if clashing:
        names = ", ".join(sorted({e["staff_initials"] for e in clashing}))
        return {
            "slot_status": "role_conflict",
            "slot_open": False,
            "reason": (
                f"{names} ({staff_role}) is already on AL on {date_str} — "
                f"only one {staff_role} can be on AL the same day."
            ),
            "existing_leave": existing_leave,
            "would_break_rules": ["max_one_per_role_on_al"],
        }

    return {
        "slot_status": "open",
        "slot_open": True,
        "reason": None,
        "existing_leave": existing_leave,
        "would_break_rules": [],
    }


@api.get("/public/request-link/{token}/check")
async def public_slot_check(
    token: str,
    date_param: str = Query(..., alias="date"),
    preference: str = Query(default="OFF"),
):
    """Public slot-availability check the staff page uses BEFORE submit
    to show a green/red hint about whether the request is likely to be
    approved."""
    doc = await _resolve_token(token)
    return await _check_leave_slot(doc["staff_initials"], date_param, preference)


@api.post("/public/request-link/{token}/submit")
async def public_submit(token: str, payload: PublicSubmitIn):
    doc = await _resolve_token(token)
    # Validate every submitted date falls inside the public window.
    today = datetime.now(timezone.utc).date()
    end_of_next_year = date(today.year + 1, 12, 31)
    for r in payload.requests:
        try:
            d = datetime.strptime(r.get("date") or "", "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(422, f"Invalid date format: {r.get('date')!r}")
        if d < today or d > end_of_next_year:
            raise HTTPException(
                422,
                f"Date {d.isoformat()} is outside the request window "
                f"({today.isoformat()} — {end_of_next_year.isoformat()})",
            )
    created: list[dict] = []
    for r in payload.requests:
        req = {
            "id": str(uuid.uuid4()),
            "staff_initials": doc["staff_initials"],
            "date": r.get("date"),
            "shift_preference": r.get("shift_preference", "OTHER"),
            "notes": r.get("notes", ""),
            "status": "pending",
            "source": "staff_link",
            "resolution_note": None,
            "resolved_at": None,
            "created_at": _now(),
        }
        await db.requests.insert_one(req)
        created.append(_strip_id(req))
    return {"created": len(created)}


# --- Mount and middleware ----------------------------------------------
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup_event():
    summary = await seed_if_empty(db)
    if summary:
        logger.info("DB seed summary: %s", summary)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
