from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pytesseract.pytesseract import TesseractNotFoundError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .algorithms import (
    can_transition_incident,
    congestion_score,
    equipment_risk,
    recommend_yard_slot,
    summarize_gate,
    validate_container_number,
)
from .config import ROOT, settings
from .database import Base, SessionLocal, engine, get_db
from .domain_services import (
    assess_reefer,
    can_transition_work_order,
    equipment_risk_methods,
    gate_visit_timeline,
    rehandle_risk,
    validate_berth_assignment,
    validate_yard_placement,
    yard_slot_analysis,
)
from .events import IdempotencyConflict, ingest_event, snapshot
from .models import (
    AuditLog,
    Berth,
    Camera,
    CameraZone,
    Container,
    ContainerMovement,
    Equipment,
    EquipmentTelemetry,
    Incident,
    IncidentNote,
    OCRJob,
    OperationalEvent,
    ReeferReading,
    RefreshToken,
    SafetyEvent,
    SimulationRun,
    Terminal,
    TruckVisit,
    User,
    VesselCall,
    WorkOrder,
    YardBlock,
    YardSlot,
)
from .public_dataset import public_port_summary
from .reports import (
    build_daily_pdf,
    build_operational_pdf,
    containers_csv,
    operational_report_csv,
    operational_report_data,
    terminal_summary,
)
from .security import (
    create_access_token,
    current_user,
    decode_token,
    new_refresh_token,
    refresh_token_hash,
    request_token,
    require_roles,
    verify_password,
)
from .seed import seed_database
from .simulation import SCENARIOS, run_scenario
from .twin_service import build_live_state, playback_window, serialize_event
from .vision import generate_container_image, generate_sample_video, process_ocr, process_video

logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
logger = logging.getLogger("harborvision")

LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 8
EXPENSIVE_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
EXPENSIVE_LIMITS: dict[str, tuple[int, int]] = {
    f"{settings.api_prefix}/ocr/process-sample": (6, 60),
    f"{settings.api_prefix}/vision/process-sample": (4, 60),
    f"{settings.api_prefix}/reports/daily.pdf": (12, 60),
    f"{settings.api_prefix}/simulation/run": (20, 60),
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        has_terminal = db.scalar(select(func.count()).select_from(Terminal)) or 0
    if not has_terminal:
        logger.info("empty database detected; seeding deterministic demonstration data")
        seed_database(reset=True)
    yield


app = FastAPI(
    title="HarborVision Twin API",
    version="2.0.0",
    description="CPU-first smart port digital twin, event replay, computer vision and operational intelligence platform.",
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    started = time.perf_counter()
    if request.url.path in EXPENSIVE_LIMITS:
        limit, window = EXPENSIVE_LIMITS[request.url.path]
        client_host = request.client.host if request.client else "unknown"
        key = f"{client_host}:{request.url.path}"
        attempts = EXPENSIVE_ATTEMPTS[key]
        now = time.monotonic()
        while attempts and now - attempts[0] > window:
            attempts.popleft()
        if len(attempts) >= limit:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded for this operation", "request_id": request_id})
        attempts.append(now)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled request error request_id=%s path=%s", request_id, request.url.path)
        raise
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class BerthAssignmentRequest(BaseModel):
    berth_id: int
    planned_start: datetime
    planned_end: datetime


class ContainerMoveRequest(BaseModel):
    to_slot_id: int
    idempotency_key: str = Field(min_length=8, max_length=120)


class IncidentTransitionRequest(BaseModel):
    status: str
    corrective_action: str | None = None
    root_cause: str | None = None
    dismissed_reason: str | None = None


class IncidentNoteRequest(BaseModel):
    note: str = Field(min_length=2, max_length=4000)


class WorkOrderTransitionRequest(BaseModel):
    status: str
    assigned_team: str | None = None
    completion_notes: str | None = None
    cancellation_reason: str | None = None


class ScenarioRequest(BaseModel):
    scenario: str
    speed_multiplier: float = Field(default=10.0, ge=0.1, le=100)


class SimulationCreateRequest(BaseModel):
    scenario: str
    speed_multiplier: float = Field(default=10.0, ge=0.1, le=100)
    random_seed: int = 20260719


class OCRCorrectionRequest(BaseModel):
    normalized_number: str
    approve: bool = True


def audit(db: Session, user: User | None, action: str, entity_type: str, entity_id: str | None, details: dict[str, Any] | None = None):
    db.add(
        AuditLog(
            organization_id=user.organization_id if user else 1,
            user_id=user.id if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details_json=json.dumps(details or {}),
        )
    )


def as_iso(value):
    return value.isoformat() if value else None


def container_dict(item: Container, db: Session | None = None):
    result = {
        "id": item.id,
        "number": item.number,
        "iso_type": item.iso_type,
        "length_ft": item.length_ft,
        "status": item.status,
        "movement_type": item.movement_type,
        "is_full": item.is_full,
        "is_hazardous": item.is_hazardous,
        "is_reefer": item.is_reefer,
        "weight_kg": item.weight_kg,
        "slot_id": item.slot_id,
        "vessel_call_id": item.vessel_call_id,
        "dwell_start": as_iso(item.dwell_start),
        "last_movement_at": as_iso(item.last_movement_at),
        "seal_status": item.seal_status,
        "damage_status": item.damage_status,
        "validation": validate_container_number(item.number),
    }
    if db and item.slot_id:
        slot = db.get(YardSlot, item.slot_id)
        block = db.get(YardBlock, slot.block_id) if slot else None
        result["location"] = {
            "block": block.code if block else None,
            "bay": slot.bay if slot else None,
            "row": slot.row if slot else None,
            "tier": slot.tier if slot else None,
        }
    return result


def twin_state(db: Session, org_id: int):
    try:
        return build_live_state(db, org_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get(f"{settings.api_prefix}/health/live", tags=["health"])
def live():
    return {"status": "ok", "service": settings.app_name, "time": datetime.now(UTC).isoformat()}


@app.get(f"{settings.api_prefix}/health/ready", tags=["health"])
def ready(db: Session = Depends(get_db)):
    components: dict[str, Any] = {}
    db.execute(text("SELECT 1"))
    components["database"] = {"status": "ok", "adapter": "sqlite" if settings.database_url.startswith("sqlite") else "postgresql"}

    probe = settings.storage_dir / ".health-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    components["storage"] = {"status": "ok", "adapter": "local-filesystem"}

    redis_status: dict[str, Any] = {"status": "not-configured", "required": False}
    if settings.redis_url:
        try:
            from redis import Redis

            client = Redis.from_url(settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
            redis_status = {"status": "ok" if client.ping() else "degraded", "required": settings.environment == "production"}
        except Exception as exc:  # readiness reports the dependency without leaking connection details
            redis_status = {"status": "unavailable", "required": settings.environment == "production", "error": type(exc).__name__}
    components["redis"] = redis_status

    heartbeat_path = settings.storage_dir / "worker-heartbeat.json"
    worker_status: dict[str, Any] = {"status": "not-started", "required": False}
    if heartbeat_path.exists():
        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            heartbeat_time = datetime.fromisoformat(heartbeat["time"])
            age = max((datetime.now(UTC) - heartbeat_time).total_seconds(), 0)
            worker_status = {
                "status": "ok" if age <= settings.worker_stale_seconds else "stale",
                "age_seconds": round(age, 1),
                "event_count": heartbeat.get("event_count"),
            }
        except (ValueError, KeyError, json.JSONDecodeError):
            worker_status = {"status": "invalid-heartbeat", "required": False}
    components["worker"] = worker_status

    required_unavailable = any(value.get("required") and value.get("status") != "ok" for value in components.values())
    return {
        "status": "degraded" if required_unavailable else "ready",
        "database": components["database"]["status"],
        "redis": components["redis"]["status"],
        "storage": components["storage"]["adapter"],
        "worker": components["worker"]["status"],
        "components": components,
        "environment": settings.environment,
    }


@app.post(f"{settings.api_prefix}/auth/login", tags=["auth"])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    key = payload.email.lower().strip()
    now_monotonic = time.monotonic()
    attempts = LOGIN_ATTEMPTS[key]
    while attempts and now_monotonic - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts; retry later")
    user = db.scalar(select(User).where(User.email == key))
    if not user or not verify_password(payload.password, user.password_hash):
        attempts.append(now_monotonic)
        if user:
            user.failed_logins += 1
            audit(db, user, "failed_login", "user", str(user.id))
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    user.failed_logins = 0
    user.last_login_at = datetime.now(UTC)
    audit(db, user, "login", "user", str(user.id))
    token = create_access_token(user.id, user.organization_id, user.role)
    raw_refresh, token_hash = new_refresh_token()
    db.add(
        RefreshToken(
            organization_id=user.organization_id,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
    )
    attempts.clear()
    db.commit()
    return {
        "access_token": token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "name": user.full_name, "role": user.role},
    }


@app.post(f"{settings.api_prefix}/auth/refresh", tags=["auth"])
def refresh_session(payload: RefreshRequest, db: Session = Depends(get_db)):
    digest = refresh_token_hash(payload.refresh_token)
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest))
    now = datetime.now(UTC)
    if not stored or stored.revoked_at is not None:
        raise HTTPException(401, "Invalid refresh token")
    expiry = stored.expires_at if stored.expires_at.tzinfo else stored.expires_at.replace(tzinfo=UTC)
    if expiry <= now:
        raise HTTPException(401, "Expired refresh token")
    user = db.get(User, stored.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Inactive user")
    raw_refresh, replacement_hash = new_refresh_token()
    stored.revoked_at = now
    stored.replaced_by_hash = replacement_hash
    db.add(
        RefreshToken(
            organization_id=user.organization_id, user_id=user.id, token_hash=replacement_hash, expires_at=now + timedelta(days=14)
        )
    )
    access = create_access_token(user.id, user.organization_id, user.role)
    audit(db, user, "refresh_token_rotated", "user", str(user.id))
    db.commit()
    return {"access_token": access, "refresh_token": raw_refresh, "token_type": "bearer"}


@app.post(f"{settings.api_prefix}/auth/logout", tags=["auth"])
def logout_session(payload: LogoutRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    digest = refresh_token_hash(payload.refresh_token)
    stored = db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == digest,
            RefreshToken.user_id == user.id,
            RefreshToken.organization_id == user.organization_id,
        )
    )
    if stored and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
    audit(db, user, "logout", "user", str(user.id))
    db.commit()
    return {"status": "logged_out"}


@app.get(f"{settings.api_prefix}/auth/me", tags=["auth"])
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "name": user.full_name, "role": user.role, "organization_id": user.organization_id}


@app.get(f"{settings.api_prefix}/dashboard", tags=["analytics"])
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = user.organization_id
    state = twin_state(db, org)
    gate = summarize_gate(db, org)
    total_slots = sum(block["capacity"] for block in state["yard_blocks"])
    occupied = sum(block["occupied"] for block in state["yard_blocks"])
    yard_utilization = occupied / total_slots if total_slots else 0
    active_vessels = [v for v in state["vessels"] if v["status"] not in {"departed", "scheduled"}]
    berth_utilization = len([v for v in active_vessels if v["berth_id"]]) / max(len(state["berths"]), 1)
    congestion = congestion_score(
        gate["queue_length"], gate["average_wait_minutes"], gate["open_lanes"], yard_utilization, berth_utilization
    )
    active_incidents = (
        db.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.organization_id == org, Incident.status.not_in(["resolved", "dismissed"]))
        )
        or 0
    )
    critical_reefers = (
        db.scalar(
            select(func.count(func.distinct(ReeferReading.container_id))).where(
                ReeferReading.organization_id == org, ReeferReading.alarm_state != "normal"
            )
        )
        or 0
    )
    return {
        "kpis": {
            "vessels_in_port": len(active_vessels),
            "berth_utilization_pct": round(berth_utilization * 100, 1),
            "yard_occupancy_pct": round(yard_utilization * 100, 1),
            "gate_queue": gate["queue_length"],
            "average_gate_wait_minutes": gate["average_wait_minutes"],
            "active_incidents": active_incidents,
            "critical_reefer_alarms": critical_reefers,
            "equipment_availability_pct": round(
                sum(e["availability"] for e in state["equipment"]) / max(len(state["equipment"]), 1) * 100, 1
            ),
            "container_registry": db.scalar(select(func.count()).select_from(Container).where(Container.organization_id == org)) or 0,
        },
        "congestion": congestion,
        "gate": gate,
        "latest_events": [
            {
                "id": e.id,
                "type": e.event_type,
                "entity": f"{e.entity_type}:{e.entity_id}",
                "time": as_iso(e.occurred_at),
                "source": e.source,
            }
            for e in db.scalars(
                select(OperationalEvent)
                .where(OperationalEvent.organization_id == org)
                .order_by(OperationalEvent.occurred_at.desc())
                .limit(12)
            )
        ],
    }


@app.get(f"{settings.api_prefix}/public-dataset/ports", tags=["public-dataset"])
def public_dataset_ports(limit: int = Query(default=24, ge=1, le=120), user: User = Depends(current_user)):
    return public_port_summary(limit=limit)


@app.get(f"{settings.api_prefix}/digital-twin/state", tags=["digital-twin"])
def digital_twin_state(at: datetime | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if at is not None:
        start = at - timedelta(hours=1)
        return playback_window(db, user.organization_id, start, at, limit=500)["state_at_end"]
    return twin_state(db, user.organization_id)


@app.get(f"{settings.api_prefix}/digital-twin/playback", tags=["digital-twin"])
def digital_twin_playback(
    start: datetime,
    end: datetime,
    limit: int = Query(500, ge=1, le=2000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        return playback_window(db, user.organization_id, start, end, limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post(f"{settings.api_prefix}/digital-twin/snapshot", tags=["digital-twin"])
def create_snapshot(user: User = Depends(require_roles("admin", "director", "analyst")), db: Session = Depends(get_db)):
    state = twin_state(db, user.organization_id)
    item = snapshot(db, user.organization_id, state)
    audit(db, user, "digital_twin_snapshot", "snapshot", None)
    db.commit()
    return {"id": item.id, "captured_at": as_iso(item.captured_at), "event_count": item.event_count}


@app.get(f"{settings.api_prefix}/vessels", tags=["vessels"])
def vessels(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(VesselCall).where(VesselCall.organization_id == user.organization_id).order_by(VesselCall.eta)).all()
    return [
        {
            "id": x.id,
            "name": x.vessel_name,
            "imo": x.imo_number,
            "voyage": x.voyage_number,
            "status": x.status,
            "berth_id": x.berth_id,
            "eta": as_iso(x.eta),
            "planned_start": as_iso(x.planned_start),
            "planned_end": as_iso(x.planned_end),
            "actual_arrival": as_iso(x.actual_arrival),
            "actual_departure": as_iso(x.actual_departure),
            "target_moves": x.target_moves,
            "actual_moves": x.actual_moves,
        }
        for x in items
    ]


@app.get(f"{settings.api_prefix}/berths", tags=["berths"])
def berths(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [
        {
            "id": x.id,
            "code": x.code,
            "name": x.name,
            "length_m": x.length_m,
            "draft_limit_m": x.draft_limit_m,
            "maintenance_start": as_iso(x.maintenance_start),
            "maintenance_end": as_iso(x.maintenance_end),
        }
        for x in db.scalars(select(Berth).where(Berth.organization_id == user.organization_id).order_by(Berth.code))
    ]


@app.put(f"{settings.api_prefix}/vessels/{{vessel_id}}/berth-assignment", tags=["vessels"])
def assign_berth(
    vessel_id: int,
    payload: BerthAssignmentRequest,
    user: User = Depends(require_roles("planner", "director")),
    db: Session = Depends(get_db),
):
    vessel = db.get(VesselCall, vessel_id)
    berth = db.get(Berth, payload.berth_id)
    if not vessel or vessel.organization_id != user.organization_id or not berth or berth.organization_id != user.organization_id:
        raise HTTPException(404, "Vessel or berth not found")
    conflicts = validate_berth_assignment(db, user.organization_id, vessel, berth, payload.planned_start, payload.planned_end)
    if conflicts:
        raise HTTPException(409, detail={"message": "Berth assignment is not operationally valid", "conflicts": conflicts})
    vessel.berth_id = berth.id
    vessel.planned_start = payload.planned_start
    vessel.planned_end = payload.planned_end
    audit(db, user, "berth_plan_changed", "vessel_call", str(vessel.id), payload.model_dump(mode="json"))
    db.commit()
    return {"status": "assigned", "vessel_id": vessel.id, "berth_id": berth.id}


@app.get(f"{settings.api_prefix}/containers", tags=["containers"])
def containers(
    q: str | None = None,
    movement_type: str | None = None,
    is_reefer: bool | None = None,
    is_hazardous: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = select(Container).where(Container.organization_id == user.organization_id)
    if q:
        query = query.where(Container.number.contains(q.upper()))
    if movement_type:
        query = query.where(Container.movement_type == movement_type)
    if is_reefer is not None:
        query = query.where(Container.is_reefer == is_reefer)
    if is_hazardous is not None:
        query = query.where(Container.is_hazardous == is_hazardous)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(Container.number).offset(offset).limit(limit)).all()
    return {"items": [container_dict(item, db) for item in items], "total": total, "limit": limit, "offset": offset}


@app.get(f"{settings.api_prefix}/containers/{{container_id}}", tags=["containers"])
def container_detail(container_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(Container, container_id)
    if not item or item.organization_id != user.organization_id:
        raise HTTPException(404, "Container not found")
    result = container_dict(item, db)
    result["movements"] = [
        {
            "id": m.id,
            "type": m.movement_type,
            "from_slot_id": m.from_slot_id,
            "to_slot_id": m.to_slot_id,
            "occurred_at": as_iso(m.occurred_at),
            "source_event_id": m.source_event_id,
        }
        for m in db.scalars(
            select(ContainerMovement).where(ContainerMovement.container_id == item.id).order_by(ContainerMovement.occurred_at.desc())
        )
    ]
    return result


@app.get(f"{settings.api_prefix}/containers/{{container_id}}/recommendations", tags=["yard"])
def slot_recommendations(container_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    container = db.get(Container, container_id)
    if not container or container.organization_id != user.organization_id:
        raise HTTPException(404, "Container not found")
    return [
        {**item.__dict__, "rehandle_risk": rehandle_risk(db, user.organization_id, container)}
        for item in recommend_yard_slot(db, user.organization_id, container)
    ]


@app.get(f"{settings.api_prefix}/containers/{{container_id}}/placement-analysis", tags=["yard"])
def container_placement_analysis(
    container_id: int, limit: int = Query(5, ge=1, le=20), user: User = Depends(current_user), db: Session = Depends(get_db)
):
    container = db.get(Container, container_id)
    if not container or container.organization_id != user.organization_id:
        raise HTTPException(404, "Container not found")
    return yard_slot_analysis(db, user.organization_id, container, limit)


@app.get(f"{settings.api_prefix}/containers/{{container_id}}/rehandle-risk", tags=["yard"])
def container_rehandle_risk(container_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    container = db.get(Container, container_id)
    if not container or container.organization_id != user.organization_id:
        raise HTTPException(404, "Container not found")
    return rehandle_risk(db, user.organization_id, container)


@app.post(f"{settings.api_prefix}/containers/{{container_id}}/move", tags=["yard"])
def move_container(
    container_id: int, payload: ContainerMoveRequest, user: User = Depends(require_roles("yard", "director")), db: Session = Depends(get_db)
):
    container = db.get(Container, container_id)
    slot = db.get(YardSlot, payload.to_slot_id)
    if not container or container.organization_id != user.organization_id or not slot or slot.organization_id != user.organization_id:
        raise HTTPException(404, "Container or slot not found")
    block = db.get(YardBlock, slot.block_id)
    if block is None:
        raise HTTPException(404, "Yard block not found")
    violations = validate_yard_placement(container, slot, block)
    if violations:
        raise HTTPException(422, detail={"message": "Placement validation failed", "violations": violations})
    old_slot_id = container.slot_id
    try:
        event = ingest_event(
            db,
            user.organization_id,
            "container_yard_move",
            "container",
            str(container.id),
            {"to_slot_id": slot.id},
            payload.idempotency_key,
            source="web",
            correlation_id=str(uuid.uuid4()),
        )
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(
        db,
        user,
        "container_moved",
        "container",
        str(container.id),
        {"from_slot_id": old_slot_id, "to_slot_id": slot.id, "event_id": event.event_id},
    )
    db.commit()
    return {"status": "moved", "container": container_dict(container, db), "event_id": event.event_id}


@app.get(f"{settings.api_prefix}/yard/blocks", tags=["yard"])
def yard_blocks(user: User = Depends(current_user), db: Session = Depends(get_db)):
    state = twin_state(db, user.organization_id)
    return state["yard_blocks"]


@app.get(f"{settings.api_prefix}/yard/blocks/{{block_id}}", tags=["yard"])
def yard_block_detail(block_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    block = db.get(YardBlock, block_id)
    if not block or block.organization_id != user.organization_id:
        raise HTTPException(404, "Block not found")
    slots = db.scalars(select(YardSlot).where(YardSlot.block_id == block.id).order_by(YardSlot.bay, YardSlot.row, YardSlot.tier)).all()
    container_by_slot = {
        c.slot_id: c
        for c in db.scalars(select(Container).where(Container.organization_id == user.organization_id, Container.slot_id.is_not(None)))
    }
    return {
        "block": {"id": block.id, "code": block.code, "kind": block.kind, "capacity": len(slots)},
        "slots": [
            {
                "id": s.id,
                "bay": s.bay,
                "row": s.row,
                "tier": s.tier,
                "occupied": s.occupied,
                "container": container_dict(container_by_slot[s.id]) if s.id in container_by_slot else None,
            }
            for s in slots
        ],
    }


@app.get(f"{settings.api_prefix}/gates/overview", tags=["gates"])
def gate_overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    summary = summarize_gate(db, user.organization_id)
    rows = db.scalars(
        select(TruckVisit).where(TruckVisit.organization_id == user.organization_id).order_by(TruckVisit.arrival_at.desc()).limit(30)
    ).all()
    summary["visits"] = [
        {
            "id": x.id,
            "plate": x.plate_number,
            "driver": x.driver_name,
            "status": x.status,
            "lane_id": x.lane_id,
            "arrival_at": as_iso(x.arrival_at),
            "processing_start": as_iso(x.processing_start),
            "exit_at": as_iso(x.exit_at),
        }
        for x in rows
    ]
    return summary


@app.get(f"{settings.api_prefix}/gates/visits/{{visit_id}}", tags=["gates"])
def gate_visit_detail(visit_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    visit = db.get(TruckVisit, visit_id)
    if not visit or visit.organization_id != user.organization_id:
        raise HTTPException(404, "Truck visit not found")
    wait_minutes = (visit.processing_start - visit.arrival_at).total_seconds() / 60 if visit.processing_start else None
    service_minutes = (
        (visit.processing_end - visit.processing_start).total_seconds() / 60 if visit.processing_end and visit.processing_start else None
    )
    turnaround_minutes = (visit.exit_at - visit.arrival_at).total_seconds() / 60 if visit.exit_at else None
    return {
        "id": visit.id,
        "plate": visit.plate_number,
        "driver": visit.driver_name,
        "status": visit.status,
        "container_id": visit.container_id,
        "lane_id": visit.lane_id,
        "timeline": gate_visit_timeline(visit),
        "metrics": {"wait_minutes": wait_minutes, "service_minutes": service_minutes, "turnaround_minutes": turnaround_minutes},
    }


@app.get(f"{settings.api_prefix}/equipment", tags=["equipment"])
def equipment_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = []
    for item in db.scalars(select(Equipment).where(Equipment.organization_id == user.organization_id).order_by(Equipment.code)):
        telemetry = list(
            db.scalars(
                select(EquipmentTelemetry)
                .where(EquipmentTelemetry.equipment_id == item.id)
                .order_by(EquipmentTelemetry.recorded_at.desc())
                .limit(24)
            )
        )[::-1]
        risk = equipment_risk(telemetry)
        latest = telemetry[-1] if telemetry else None
        result.append(
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "type": item.equipment_type,
                "state": item.state,
                "availability": item.availability,
                "latest": {
                    "time": as_iso(latest.recorded_at),
                    "temperature_c": latest.temperature_c,
                    "vibration_mm_s": latest.vibration_mm_s,
                    "load_pct": latest.load_pct,
                }
                if latest
                else None,
                "risk": risk,
            }
        )
    return result


@app.get(f"{settings.api_prefix}/equipment/{{equipment_id}}", tags=["equipment"])
def equipment_detail(equipment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(Equipment, equipment_id)
    if not item or item.organization_id != user.organization_id:
        raise HTTPException(404, "Equipment not found")
    telemetry = list(
        db.scalars(
            select(EquipmentTelemetry)
            .where(EquipmentTelemetry.equipment_id == item.id)
            .order_by(EquipmentTelemetry.recorded_at.desc())
            .limit(120)
        )
    )[::-1]
    return {
        "equipment": {
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "type": item.equipment_type,
            "state": item.state,
            "availability": item.availability,
        },
        "risk": equipment_risk_methods(telemetry),
        "telemetry": [
            {
                "time": as_iso(x.recorded_at),
                "temperature_c": x.temperature_c,
                "vibration_mm_s": x.vibration_mm_s,
                "hydraulic_bar": x.hydraulic_bar,
                "load_pct": x.load_pct,
            }
            for x in telemetry
        ],
    }


@app.get(f"{settings.api_prefix}/reefers", tags=["reefers"])
def reefers(user: User = Depends(current_user), db: Session = Depends(get_db)):
    containers = db.scalars(
        select(Container).where(Container.organization_id == user.organization_id, Container.is_reefer.is_(True)).order_by(Container.number)
    ).all()
    result = []
    for container in containers:
        latest = db.scalar(
            select(ReeferReading).where(ReeferReading.container_id == container.id).order_by(ReeferReading.recorded_at.desc())
        )
        if latest:
            result.append(
                {
                    "container_id": container.id,
                    "number": container.number,
                    "target_c": latest.target_c,
                    "actual_c": latest.actual_c,
                    "power_on": latest.power_on,
                    "door_open": latest.door_open,
                    "alarm_state": latest.alarm_state,
                    "last_reading": as_iso(latest.recorded_at),
                    "deviation_c": round(latest.actual_c - latest.target_c, 2),
                    "assessment": assess_reefer(
                        list(
                            db.scalars(
                                select(ReeferReading)
                                .where(ReeferReading.container_id == container.id)
                                .order_by(ReeferReading.recorded_at.desc())
                                .limit(24)
                            )
                        )[::-1]
                    ),
                }
            )
    return result


@app.get(f"{settings.api_prefix}/safety-events", tags=["safety"])
def safety_events(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(
        select(SafetyEvent).where(SafetyEvent.organization_id == user.organization_id).order_by(SafetyEvent.detected_at.desc()).limit(100)
    ).all()
    return [
        {
            "id": x.id,
            "camera_id": x.camera_id,
            "zone_id": x.zone_id,
            "event_type": x.event_type,
            "severity": x.severity,
            "track_id": x.track_id,
            "confidence": x.confidence,
            "detected_at": as_iso(x.detected_at),
            "evidence_path": x.evidence_path,
            "evidence_url": f"/artifacts/{x.evidence_path.replace('data/generated/', '')}",
            "review_status": x.review_status,
            "details": json.loads(x.details_json),
        }
        for x in items
    ]


@app.post(f"{settings.api_prefix}/vision/process-sample", tags=["vision"])
def vision_process_sample(user: User = Depends(require_roles("safety", "admin", "director")), db: Session = Depends(get_db)):
    camera = db.scalar(select(Camera).where(Camera.organization_id == user.organization_id).order_by(Camera.id))
    zone = db.scalar(select(CameraZone).where(CameraZone.camera_id == camera.id)) if camera else None
    if not camera or not zone:
        raise HTTPException(404, "Seeded camera or zone not found")
    video_path = ROOT / camera.source
    if not video_path.exists():
        generate_sample_video(video_path)
    result = process_video(db, user.organization_id, camera, zone, video_path)
    audit(db, user, "sample_video_processed", "camera", str(camera.id), result)
    db.commit()
    return result


@app.post(f"{settings.api_prefix}/ocr/process-sample", tags=["ocr"])
def ocr_process_sample(user: User = Depends(require_roles("admin", "yard", "director")), db: Session = Depends(get_db)):
    container = db.scalar(select(Container).where(Container.organization_id == user.organization_id).order_by(Container.id))
    if container is None:
        raise HTTPException(404, "No container is available for OCR sampling")
    image_path = ROOT / "data" / "sample" / "container-code-sample.png"
    if not image_path.exists():
        generate_container_image(container.number, image_path)
    try:
        result = process_ocr(db, user.organization_id, image_path)
    except TesseractNotFoundError as exc:
        raise HTTPException(503, "Tesseract OCR is not installed or is not available on PATH") from exc
    audit(db, user, "ocr_processed", "ocr_job", str(result["job_id"]), result)
    db.commit()
    return result


@app.get(f"{settings.api_prefix}/ocr/jobs", tags=["ocr"])
def ocr_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [
        {
            "id": x.id,
            "source_path": x.source_path,
            "crop_path": x.crop_path,
            "enhanced_path": x.enhanced_path,
            "raw_text": x.raw_text,
            "normalized_number": x.normalized_number,
            "confidence": x.confidence,
            "validation_status": x.validation_status,
            "candidates": json.loads(x.candidates_json),
            "reviewer_id": x.reviewer_id,
            "reviewed_at": as_iso(x.reviewed_at),
            "created_at": as_iso(x.created_at),
        }
        for x in db.scalars(select(OCRJob).where(OCRJob.organization_id == user.organization_id).order_by(OCRJob.created_at.desc()))
    ]


@app.put(f"{settings.api_prefix}/ocr/jobs/{{job_id}}", tags=["ocr"])
def correct_ocr(
    job_id: int,
    payload: OCRCorrectionRequest,
    user: User = Depends(require_roles("admin", "yard", "director")),
    db: Session = Depends(get_db),
):
    job = db.get(OCRJob, job_id)
    if not job or job.organization_id != user.organization_id:
        raise HTTPException(404, "OCR job not found")
    validation = validate_container_number(payload.normalized_number)
    if payload.approve and not validation["valid"]:
        raise HTTPException(422, detail={"message": "Cannot approve invalid ISO 6346 number", "validation": validation})
    job.normalized_number = validation["number"]
    job.validation_status = "approved" if payload.approve else "rejected"
    job.reviewer_id = user.id
    job.reviewed_at = datetime.now(UTC)
    audit(db, user, "ocr_corrected", "ocr_job", str(job.id), {"number": job.normalized_number, "status": job.validation_status})
    db.commit()
    return {"id": job.id, "normalized_number": job.normalized_number, "validation_status": job.validation_status}


@app.get(f"{settings.api_prefix}/incidents", tags=["incidents"])
def incidents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Incident).where(Incident.organization_id == user.organization_id).order_by(Incident.created_at.desc())).all()
    return [
        {
            "id": x.id,
            "title": x.title,
            "type": x.incident_type,
            "severity": x.severity,
            "status": x.status,
            "assigned_to": x.assigned_to,
            "assigned_team": x.assigned_team,
            "due_at": as_iso(x.due_at),
            "dismissed_reason": x.dismissed_reason,
            "reopened_count": x.reopened_count,
            "source_event_id": x.source_event_id,
            "created_at": as_iso(x.created_at),
            "resolved_at": as_iso(x.resolved_at),
            "corrective_action": x.corrective_action,
            "root_cause": x.root_cause,
        }
        for x in items
    ]


@app.post(f"{settings.api_prefix}/incidents/{{incident_id}}/transition", tags=["incidents"])
def incident_transition(
    incident_id: int,
    payload: IncidentTransitionRequest,
    user: User = Depends(require_roles("safety", "director", "admin")),
    db: Session = Depends(get_db),
):
    incident = db.get(Incident, incident_id)
    if not incident or incident.organization_id != user.organization_id:
        raise HTTPException(404, "Incident not found")
    if not can_transition_incident(incident.status, payload.status):
        raise HTTPException(409, detail={"message": "Invalid incident transition", "current": incident.status, "target": payload.status})
    if payload.status == "dismissed" and not payload.dismissed_reason:
        raise HTTPException(422, "A dismissal reason is required")
    previous = incident.status
    incident.status = payload.status
    if previous in {"resolved", "dismissed"} and payload.status == "open":
        incident.reopened_count += 1
    if payload.corrective_action is not None:
        incident.corrective_action = payload.corrective_action
    if payload.root_cause is not None:
        incident.root_cause = payload.root_cause
    incident.dismissed_reason = payload.dismissed_reason if payload.status == "dismissed" else incident.dismissed_reason
    incident.resolved_at = datetime.now(UTC) if payload.status == "resolved" else None
    audit(db, user, "incident_status_changed", "incident", str(incident.id), {"from": previous, "to": payload.status})
    db.commit()
    return {"id": incident.id, "status": incident.status, "resolved_at": as_iso(incident.resolved_at)}


@app.get(f"{settings.api_prefix}/work-orders", tags=["maintenance"])
def work_orders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [
        {
            "id": x.id,
            "equipment_id": x.equipment_id,
            "title": x.title,
            "description": x.description,
            "priority": x.priority,
            "status": x.status,
            "assigned_team": x.assigned_team,
            "checklist": json.loads(x.checklist_json or "[]"),
            "completion_notes": x.completion_notes,
            "due_at": as_iso(x.due_at),
            "created_at": as_iso(x.created_at),
            "completed_at": as_iso(x.completed_at),
            "verified_at": as_iso(x.verified_at),
        }
        for x in db.scalars(
            select(WorkOrder).where(WorkOrder.organization_id == user.organization_id).order_by(WorkOrder.created_at.desc())
        )
    ]


@app.get(f"{settings.api_prefix}/incidents/{{incident_id}}", tags=["incidents"])
def incident_detail(incident_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(Incident, incident_id)
    if not item or item.organization_id != user.organization_id:
        raise HTTPException(404, "Incident not found")
    notes = list(db.scalars(select(IncidentNote).where(IncidentNote.incident_id == item.id).order_by(IncidentNote.created_at)))
    return {
        "id": item.id,
        "title": item.title,
        "type": item.incident_type,
        "severity": item.severity,
        "status": item.status,
        "assigned_to": item.assigned_to,
        "assigned_team": item.assigned_team,
        "due_at": as_iso(item.due_at),
        "corrective_action": item.corrective_action,
        "root_cause": item.root_cause,
        "dismissed_reason": item.dismissed_reason,
        "created_at": as_iso(item.created_at),
        "resolved_at": as_iso(item.resolved_at),
        "notes": [{"id": n.id, "user_id": n.user_id, "note": n.note, "created_at": as_iso(n.created_at)} for n in notes],
    }


@app.post(f"{settings.api_prefix}/incidents/{{incident_id}}/notes", tags=["incidents"])
def add_incident_note(
    incident_id: int,
    payload: IncidentNoteRequest,
    user: User = Depends(require_roles("safety", "director", "admin")),
    db: Session = Depends(get_db),
):
    item = db.get(Incident, incident_id)
    if not item or item.organization_id != user.organization_id:
        raise HTTPException(404, "Incident not found")
    note = IncidentNote(organization_id=user.organization_id, incident_id=item.id, user_id=user.id, note=payload.note)
    db.add(note)
    db.flush()
    audit(db, user, "incident_note_added", "incident", str(item.id), {"note_id": note.id})
    db.commit()
    db.refresh(note)
    return {"id": note.id, "note": note.note, "created_at": as_iso(note.created_at)}


@app.post(f"{settings.api_prefix}/work-orders/{{work_order_id}}/transition", tags=["maintenance"])
def transition_work_order(
    work_order_id: int,
    payload: WorkOrderTransitionRequest,
    user: User = Depends(require_roles("admin", "director")),
    db: Session = Depends(get_db),
):
    item = db.get(WorkOrder, work_order_id)
    if not item or item.organization_id != user.organization_id:
        raise HTTPException(404, "Work order not found")
    if not can_transition_work_order(item.status, payload.status):
        raise HTTPException(409, detail={"message": "Invalid work-order transition", "current": item.status, "target": payload.status})
    if payload.status == "cancelled" and not payload.cancellation_reason:
        raise HTTPException(422, "Cancellation reason is required")
    if payload.status == "completed" and not payload.completion_notes:
        raise HTTPException(422, "Completion notes are required")
    previous = item.status
    item.status = payload.status
    if payload.assigned_team is not None:
        item.assigned_team = payload.assigned_team
    if payload.completion_notes is not None:
        item.completion_notes = payload.completion_notes
    if payload.cancellation_reason is not None:
        item.cancellation_reason = payload.cancellation_reason
    item.completed_at = datetime.now(UTC) if payload.status == "completed" else item.completed_at
    item.verified_at = datetime.now(UTC) if payload.status == "verified" else item.verified_at
    audit(db, user, "work_order_status_changed", "work_order", str(item.id), {"from": previous, "to": payload.status})
    db.commit()
    return {"id": item.id, "status": item.status, "completed_at": as_iso(item.completed_at), "verified_at": as_iso(item.verified_at)}


@app.get(f"{settings.api_prefix}/analytics/kpis", tags=["analytics"])
def analytics(user: User = Depends(current_user), db: Session = Depends(get_db)):
    org = user.organization_id
    vessels = list(db.scalars(select(VesselCall).where(VesselCall.organization_id == org)))
    completed_turnarounds = [
        (v.actual_departure - v.actual_arrival).total_seconds() / 3600 for v in vessels if v.actual_departure and v.actual_arrival
    ]
    slots = list(db.scalars(select(YardSlot).where(YardSlot.organization_id == org)))
    containers_list = list(db.scalars(select(Container).where(Container.organization_id == org)))
    visits = list(db.scalars(select(TruckVisit).where(TruckVisit.organization_id == org)))
    truck_turnarounds = [(v.exit_at - v.arrival_at).total_seconds() / 60 for v in visits if v.exit_at]
    completed_moves = sum(v.actual_moves for v in vessels)
    operation_hours = sum(
        max((v.planned_end - v.planned_start).total_seconds() / 3600, 0.1) for v in vessels if v.planned_end and v.planned_start
    )
    reefer_latest = []
    for container in [c for c in containers_list if c.is_reefer]:
        latest = db.scalar(
            select(ReeferReading).where(ReeferReading.container_id == container.id).order_by(ReeferReading.recorded_at.desc())
        )
        if latest:
            reefer_latest.append(latest)
    return {
        "vessel_turnaround_hours": round(sum(completed_turnarounds) / len(completed_turnarounds), 2) if completed_turnarounds else 0,
        "yard_utilization_pct": round(sum(1 for s in slots if s.occupied) / max(len(slots), 1) * 100, 2),
        "container_dwell_days": round(
            sum(
                (datetime.now(UTC).replace(tzinfo=None) - c.dwell_start.replace(tzinfo=None)).total_seconds() / 86400
                for c in containers_list
            )
            / max(len(containers_list), 1),
            2,
        ),
        "truck_turnaround_minutes": round(sum(truck_turnarounds) / len(truck_turnarounds), 2) if truck_turnarounds else 0,
        "crane_moves_per_hour": round(completed_moves / max(operation_hours, 1), 2),
        "gate_throughput": sum(1 for v in visits if v.status == "completed"),
        "equipment_availability_pct": round(
            (db.scalar(select(func.avg(Equipment.availability)).where(Equipment.organization_id == org)) or 0) * 100, 2
        ),
        "reefer_compliance_pct": round(sum(1 for r in reefer_latest if r.alarm_state == "normal") / max(len(reefer_latest), 1) * 100, 2),
        "appointment_compliance_pct": round(
            sum(1 for v in visits if abs((v.arrival_at - v.appointment_at).total_seconds()) <= 15 * 60) / max(len(visits), 1) * 100, 2
        ),
        "active_incident_rate_per_1000_moves": round(
            (
                db.scalar(
                    select(func.count())
                    .select_from(Incident)
                    .where(Incident.organization_id == org, Incident.status.not_in(["resolved", "dismissed"]))
                )
                or 0
            )
            / max(completed_moves, 1)
            * 1000,
            3,
        ),
        "source": "calculated from persisted database records",
    }


@app.get(f"{settings.api_prefix}/reports/daily.pdf", tags=["reports"])
def daily_report(user: User = Depends(current_user), db: Session = Depends(get_db)):
    path = build_daily_pdf(db, user.organization_id)
    audit(db, user, "data_export", "report", "daily-terminal-operations", {"format": "pdf"})
    db.commit()
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get(f"{settings.api_prefix}/reports/containers.csv", tags=["reports"])
def container_export(user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = containers_csv(db, user.organization_id)
    audit(db, user, "data_export", "containers", None, {"format": "csv"})
    db.commit()
    return Response(data, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=containers.csv"})


@app.get(f"{settings.api_prefix}/reports/daily.json", tags=["reports"])
def daily_json(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return terminal_summary(db, user.organization_id)


@app.get(f"{settings.api_prefix}/reports/{{report_name}}/{{format_name}}", tags=["reports"])
def operational_report(report_name: str, format_name: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        data = operational_report_data(db, user.organization_id, report_name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    audit(db, user, "data_export", "report", report_name, {"format": format_name})
    db.commit()
    if format_name == "json":
        return data
    if format_name == "csv":
        return Response(
            operational_report_csv(data), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={report_name}.csv"}
        )
    if format_name == "pdf":
        path = build_operational_pdf(db, user.organization_id, report_name)
        return FileResponse(path, media_type="application/pdf", filename=path.name)
    raise HTTPException(422, "Supported report formats are pdf, csv and json")


@app.get(f"{settings.api_prefix}/simulation/scenarios", tags=["simulation"])
def simulation_scenarios(user: User = Depends(current_user)):
    return sorted(SCENARIOS)


@app.post(f"{settings.api_prefix}/simulation/runs", tags=["simulation"])
def create_simulation_run(
    payload: SimulationCreateRequest,
    user: User = Depends(require_roles("admin", "director", "planner", "yard", "safety")),
    db: Session = Depends(get_db),
):
    if payload.scenario not in SCENARIOS:
        raise HTTPException(422, f"Unknown scenario: {payload.scenario}")
    item = SimulationRun(
        organization_id=user.organization_id,
        scenario=payload.scenario,
        status="created",
        speed_multiplier=payload.speed_multiplier,
        random_seed=payload.random_seed,
        simulated_time=datetime.now(UTC),
    )
    db.add(item)
    audit(db, user, "simulation_created", "simulation_run", None, payload.model_dump())
    db.commit()
    db.refresh(item)
    return {"id": item.id, "scenario": item.scenario, "status": item.status, "event_count": item.event_count}


@app.post(f"{settings.api_prefix}/simulation/runs/{{run_id}}/{{action}}", tags=["simulation"])
def control_simulation_run(
    run_id: int,
    action: str,
    user: User = Depends(require_roles("admin", "director", "planner", "yard", "safety")),
    db: Session = Depends(get_db),
):
    item = db.get(SimulationRun, run_id)
    if not item or item.organization_id != user.organization_id:
        raise HTTPException(404, "Simulation run not found")
    allowed = {
        "start": {"created", "paused"},
        "pause": {"running"},
        "resume": {"paused"},
        "reset": {"created", "paused", "running", "completed", "failed"},
        "advance": {"running"},
    }
    if action not in allowed or item.status not in allowed[action]:
        raise HTTPException(409, detail={"message": "Invalid simulation transition", "status": item.status, "action": action})
    if action in {"start", "resume"}:
        item.status = "running"
    elif action == "pause":
        item.status = "paused"
    elif action == "reset":
        item.status = "created"
        item.event_count = 0
        item.error_message = None
        item.simulated_time = datetime.now(UTC)
    elif action == "advance":
        try:
            result = run_scenario(db, user.organization_id, item.scenario, item.speed_multiplier)
            item.event_count += int(result["events_created"])
            item.simulated_time = datetime.fromisoformat(result["simulation_time"])
            item.status = "completed"
        except Exception as exc:
            item.status = "failed"
            item.error_message = str(exc)
            db.commit()
            raise
    item.updated_at = datetime.now(UTC)
    audit(db, user, f"simulation_{action}", "simulation_run", str(item.id), {"status": item.status, "event_count": item.event_count})
    db.commit()
    return {
        "id": item.id,
        "scenario": item.scenario,
        "status": item.status,
        "event_count": item.event_count,
        "simulated_time": as_iso(item.simulated_time),
        "error": item.error_message,
    }


@app.post(f"{settings.api_prefix}/simulation/run", tags=["simulation"])
def simulate(
    payload: ScenarioRequest,
    user: User = Depends(require_roles("admin", "director", "planner", "yard", "safety")),
    db: Session = Depends(get_db),
):
    try:
        result = run_scenario(db, user.organization_id, payload.scenario, payload.speed_multiplier)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(db, user, "simulation_run", "scenario", payload.scenario, result)
    db.commit()
    return result


@app.get(f"{settings.api_prefix}/audit", tags=["audit"])
def audit_logs(
    limit: int = Query(100, ge=1, le=500), user: User = Depends(require_roles("admin", "director")), db: Session = Depends(get_db)
):
    items = db.scalars(
        select(AuditLog).where(AuditLog.organization_id == user.organization_id).order_by(AuditLog.created_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": x.id,
            "user_id": x.user_id,
            "action": x.action,
            "entity_type": x.entity_type,
            "entity_id": x.entity_id,
            "details": json.loads(x.details_json),
            "created_at": as_iso(x.created_at),
        }
        for x in items
    ]


@app.get(f"{settings.api_prefix}/events", tags=["events"])
def operational_events(
    event_type: str | None = None,
    entity_type: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(100, ge=1, le=1000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = select(OperationalEvent).where(OperationalEvent.organization_id == user.organization_id)
    if event_type:
        query = query.where(OperationalEvent.event_type == event_type)
    if entity_type:
        query = query.where(OperationalEvent.entity_type == entity_type)
    if start:
        query = query.where(OperationalEvent.occurred_at >= start)
    if end:
        query = query.where(OperationalEvent.occurred_at <= end)
    items = db.scalars(query.order_by(OperationalEvent.occurred_at.desc(), OperationalEvent.id.desc()).limit(limit)).all()
    return [serialize_event(item) for item in items]


@app.get(f"{settings.api_prefix}/events/stream", tags=["realtime"])
async def event_stream(request: Request):
    token = request_token(request)
    if not token:
        raise HTTPException(401, "Token required")
    payload = decode_token(token)
    org_id = int(payload["org"])

    async def generator():
        last_id = 0
        while True:
            if await request.is_disconnected():
                break
            with SessionLocal() as db:
                events = db.scalars(
                    select(OperationalEvent)
                    .where(OperationalEvent.organization_id == org_id, OperationalEvent.id > last_id)
                    .order_by(OperationalEvent.id)
                    .limit(20)
                ).all()
                for event in events:
                    last_id = event.id
                    data = {
                        "id": event.id,
                        "type": event.event_type,
                        "entity_type": event.entity_type,
                        "entity_id": event.entity_id,
                        "occurred_at": as_iso(event.occurred_at),
                        "processing_status": event.processing_status,
                        "correlation_id": event.correlation_id,
                        "payload": json.loads(event.payload_json),
                    }
                    yield f"id: {event.id}\nevent: operational\ndata: {json.dumps(data)}\n\n"
            yield f"event: heartbeat\ndata: {json.dumps({'time': datetime.now(UTC).isoformat()})}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Static artifacts and single-page operations console.
web_dir = ROOT / "apps" / "web"
app.mount("/assets", StaticFiles(directory=web_dir), name="assets")
app.mount("/artifacts", StaticFiles(directory=settings.storage_dir), name="artifacts")


@app.get("/", include_in_schema=False)
def web_index():
    return FileResponse(web_dir / "index.html")


@app.get("/{path:path}", include_in_schema=False)
def web_fallback(path: str):
    target = web_dir / path
    if target.is_file():
        return FileResponse(target)
    return FileResponse(web_dir / "index.html")
