from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import json
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import Any, List
import uuid
from datetime import datetime, timezone

from solver.rota_solver import solve_rota


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection (kept alive for future phases; not used in Phase 0)
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Phase 0 seed file
SEED_PATH = ROOT_DIR / "seed" / "grizedale.json"

# Create the main app and a /api router
app = FastAPI(
    title="Grizedale Rota Builder API",
    description="Phase 0 — backend-only OR-Tools constraint solver",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
api_router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Legacy status check models (template - keep for compatibility)
# ---------------------------------------------------------------------------
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


@api_router.get("/")
async def root():
    return {"message": "Grizedale Rota Builder API — Phase 0"}


@api_router.get("/health")
async def health():
    return {"status": "ok"}


@api_router.get("/solver/seed")
async def get_solver_seed() -> dict[str, Any]:
    """Return the Grizedale seed payload (for dev/testing)."""
    if not SEED_PATH.exists():
        raise HTTPException(status_code=500, detail="Seed file missing")
    return json.loads(SEED_PATH.read_text())


@api_router.post("/solver/generate")
async def post_solver_generate(payload: dict[str, Any]) -> JSONResponse:
    """Run the CP-SAT rota solver against the supplied input.

    The endpoint accepts a free-form JSON payload that follows the schema
    documented in the project README (rota_start_date, weeks, staff[],
    leave[], locked_cells[], on_call[], avoid_pairs[], rules{}).
    """
    if "staff" not in payload or "rota_start_date" not in payload:
        raise HTTPException(
            status_code=400,
            detail="payload must include 'staff' and 'rota_start_date'",
        )
    time_limit = int(payload.get("solver_time_limit_s", 10))
    result = solve_rota(payload, time_limit_s=time_limit)
    status_code = 200 if result.get("success") else 422
    return JSONResponse(status_code=status_code, content=result)


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    _ = await db.status_checks.insert_one(doc)
    return status_obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    return status_checks


# Mount router and middleware
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
