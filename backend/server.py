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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
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


class RequestBulkPatch(BaseModel):
    ids: list[str]
    status: str
    resolution_note: str | None = None


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
    return await db.staff.find({}, {"_id": 0, "password_hash": 0}).to_list(1000)


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

    # Locked check
    if found and found.get("locked") and patch.locked is not False:
        # Locked cells can only be changed if explicitly unlocking
        # in the same patch (locked=False) OR if shift is unchanged.
        if patch.shift != found["shift"] and patch.locked is None:
            raise HTTPException(status_code=409, detail="Cell is locked. Unlock first or pass locked=false in the patch.")

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

    # 5. Solve
    time_limit = int(payload.get("solver_time_limit_s", 12))
    result = solve_rota(payload, time_limit_s=time_limit)

    if not result.get("success"):
        return JSONResponse(status_code=422, content={
            "success": False,
            "reason": result.get("reason"),
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
    return created


@api.delete("/leave/{leave_id}")
async def delete_leave(leave_id: str, current=Depends(auth_required)):
    res = await db.leave.delete_one({"id": leave_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Leave not found")
    return {"success": True}


# ============================================================================
# Requests (Phase 2)
# ============================================================================
@api.get("/requests")
async def list_requests(current=Depends(auth_required), status: str | None = None):
    q = {"status": status} if status else {}
    return await db.requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(10000)


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


async def _resolve_request(req: dict, status: str, resolution_note: str | None) -> dict:
    update = {
        "status": status,
        "resolution_note": resolution_note,
        "resolved_at": _now(),
    }
    res = await db.requests.find_one_and_update(
        {"id": req["id"]}, {"$set": update},
        return_document=True, projection={"_id": 0},
    )
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
        return await _resolve_request(existing, patch.status, patch.resolution_note)
    update = {k: v for k, v in patch.model_dump().items() if v is not None}
    res = await db.requests.find_one_and_update(
        {"id": req_id}, {"$set": update},
        return_document=True, projection={"_id": 0},
    )
    return res


@api.post("/requests/bulk")
async def bulk_patch_requests(payload: RequestBulkPatch, current=Depends(auth_required)):
    updated = []
    leave_created = 0
    for rid in payload.ids:
        existing = await db.requests.find_one({"id": rid}, {"_id": 0})
        if not existing:
            continue
        before_leave_count = await db.leave.count_documents({})
        result = await _resolve_request(existing, payload.status, payload.resolution_note)
        after_leave_count = await db.leave.count_documents({})
        if after_leave_count > before_leave_count:
            leave_created += 1
        if result:
            updated.append(result)
    return {"updated": updated, "leave_created": leave_created}


# ============================================================================
# Request tokens (Phase 2)
# ============================================================================
@api.get("/request-tokens")
async def list_tokens(current=Depends(auth_required)):
    return await db.request_tokens.find({"revoked": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@api.post("/request-tokens")
async def create_token(payload: TokenCreate, current=Depends(auth_required)):
    token = secrets.token_urlsafe(24)
    doc = {
        "id": str(uuid.uuid4()),
        "token": token,
        "staff_initials": payload.staff_initials,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)).isoformat(),
        "revoked": False,
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
    settings = await db.settings.find_one({}, {"_id": 0}) or {}
    start = settings.get("rota_start_date_default", "2026-04-20")
    weeks = settings.get("rota_length_weeks", 4)
    end_dt = datetime.strptime(start, "%Y-%m-%d") + timedelta(days=weeks * 7 - 1)
    return {
        "staff_initials": doc["staff_initials"],
        "name": staff.get("full_name") if staff else doc["staff_initials"],
        "valid_until": doc["expires_at"],
        "current_rota_window": {"from": start, "to": end_dt.strftime("%Y-%m-%d")},
    }


@api.post("/public/request-link/{token}/submit")
async def public_submit(token: str, payload: PublicSubmitIn):
    doc = await _resolve_token(token)
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
