"""Grizedale Rota Builder — Phase 1 backend.

Wires:
    /api/health
    /api/auth/login, /register, /me, /logout
    /api/staff (CRUD)
    /api/service-users (CRUD)
    /api/rules (GET, PUT)
    /api/settings (GET, PUT)
    /api/admins (GET, POST, DELETE)
    /api/solver/seed (live, from Mongo)
    /api/solver/generate (uses Mongo by default; accepts override JSON body)
    /api/docs (FastAPI Swagger)
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
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
    description="Phase 1 — auth, persistence, CRUD, solver",
    version="0.2.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
api = APIRouter(prefix="/api")
auth_required = make_current_user_dep(_get_db)


# --- Helpers ------------------------------------------------------------
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


# ============================================================================
# Health
# ============================================================================
@api.get("/")
async def root():
    return {"message": "Grizedale Rota Builder API — Phase 1"}


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
    """Admin-only — creates a new admin user."""
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {
        "id": new_user_id(),
        "email": email,
        "name": payload.name,
        "role": payload.role or "admin",
        "password_hash": hash_password(payload.password),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.users.insert_one(doc)
    safe = {k: v for k, v in doc.items() if k != "password_hash"}
    return safe


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
    docs = await db.staff.find({}, {"_id": 0, "password_hash": 0}).to_list(1000)
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
        {"id": staff_id},
        {"$set": update},
        return_document=True,
        projection={"_id": 0},
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
        {"id": su_id},
        {"$set": update},
        return_document=True,
        projection={"_id": 0},
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
# Rules
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
    update = {"rules": payload["rules"], "updated_at": _now()}
    doc = await db.rules_config.find_one_and_update(
        {},
        {"$set": update},
        return_document=True,
        projection={"_id": 0},
        upsert=True,
    )
    return doc


# ============================================================================
# Settings
# ============================================================================
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
        {},
        {"$set": payload},
        return_document=True,
        projection={"_id": 0},
        upsert=True,
    )
    return doc


# ============================================================================
# Admins
# ============================================================================
@api.get("/admins")
async def list_admins(current=Depends(auth_required)):
    docs = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(1000)
    return docs


@api.post("/admins")
async def create_admin(payload: RegisterIn, current=Depends(auth_required)):
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {
        "id": new_user_id(),
        "email": email,
        "name": payload.name,
        "role": payload.role or "admin",
        "password_hash": hash_password(payload.password),
        "created_at": _now(),
        "updated_at": _now(),
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
    """Live solver input assembled from current Mongo state."""
    return await build_solver_payload(db)


@api.post("/solver/generate")
async def post_solver_generate(payload: dict[str, Any] | None = None, current=Depends(auth_required)):
    """Run the solver. If `staff` not provided, builds payload from Mongo."""
    if not payload or not payload.get("staff"):
        payload = await build_solver_payload(db, override_start_date=(payload or {}).get("rota_start_date"))
    if "staff" not in payload or "rota_start_date" not in payload:
        raise HTTPException(status_code=400, detail="payload must include 'staff' and 'rota_start_date'")
    time_limit = int(payload.get("solver_time_limit_s", 10))
    result = solve_rota(payload, time_limit_s=time_limit)
    status_code = 200 if result.get("success") else 422
    return JSONResponse(status_code=status_code, content=result)


# --- Mount and middleware ----------------------------------------------
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Logging + startup -------------------------------------------------
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
