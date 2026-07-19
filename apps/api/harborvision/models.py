from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Terminal(Base):
    __tablename__ = "terminals"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    geometry_json: Mapped[str] = mapped_column(Text, default="{}")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(40), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Berth(Base):
    __tablename__ = "berths"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(80))
    length_m: Mapped[float] = mapped_column(Float)
    draft_limit_m: Mapped[float] = mapped_column(Float, default=14.0)
    maintenance_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    maintenance_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("terminal_id", "code"),)


class VesselCall(Base):
    __tablename__ = "vessel_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"), index=True)
    berth_id: Mapped[int | None] = mapped_column(ForeignKey("berths.id"), nullable=True, index=True)
    vessel_name: Mapped[str] = mapped_column(String(120), index=True)
    imo_number: Mapped[str] = mapped_column(String(20), unique=True)
    voyage_number: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(40), index=True)
    vessel_length_m: Mapped[float] = mapped_column(Float, default=300.0)
    draft_m: Mapped[float] = mapped_column(Float, default=12.0)
    eta: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_departure: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operation_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operation_completed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delay_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_moves: Mapped[int] = mapped_column(Integer, default=0)
    actual_moves: Mapped[int] = mapped_column(Integer, default=0)
    x: Mapped[float] = mapped_column(Float, default=0)
    y: Mapped[float] = mapped_column(Float, default=0)


class YardBlock(Base):
    __tablename__ = "yard_blocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"), index=True)
    code: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="general")
    capacity: Mapped[int] = mapped_column(Integer)
    max_tier: Mapped[int] = mapped_column(Integer, default=4)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    allocation: Mapped[str] = mapped_column(String(30), default="mixed")
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("terminal_id", "code"),)


class YardSlot(Base):
    __tablename__ = "yard_slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("yard_blocks.id"), index=True)
    bay: Mapped[int] = mapped_column(Integer)
    row: Mapped[int] = mapped_column(Integer)
    tier: Mapped[int] = mapped_column(Integer)
    max_weight_kg: Mapped[float] = mapped_column(Float, default=36_000.0)
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occupied: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    __table_args__ = (UniqueConstraint("block_id", "bay", "row", "tier"),)


class Container(Base):
    __tablename__ = "containers"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    number: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    iso_type: Mapped[str] = mapped_column(String(10))
    length_ft: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    movement_type: Mapped[str] = mapped_column(String(30), index=True)
    is_full: Mapped[bool] = mapped_column(Boolean, default=True)
    is_hazardous: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_reefer: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    slot_id: Mapped[int | None] = mapped_column(ForeignKey("yard_slots.id"), nullable=True, index=True)
    vessel_call_id: Mapped[int | None] = mapped_column(ForeignKey("vessel_calls.id"), nullable=True)
    dwell_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_movement_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    seal_status: Mapped[str] = mapped_column(String(20), default="sealed")
    damage_status: Mapped[str] = mapped_column(String(20), default="clear")
    retrieval_priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    expected_retrieval_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContainerMovement(Base):
    __tablename__ = "container_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    container_id: Mapped[int] = mapped_column(ForeignKey("containers.id"), index=True)
    from_slot_id: Mapped[int | None] = mapped_column(ForeignKey("yard_slots.id"), nullable=True)
    to_slot_id: Mapped[int | None] = mapped_column(ForeignKey("yard_slots.id"), nullable=True)
    movement_type: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GateLane(Base):
    __tablename__ = "gate_lanes"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(20))
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)


class TruckVisit(Base):
    __tablename__ = "truck_visits"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    lane_id: Mapped[int] = mapped_column(ForeignKey("gate_lanes.id"), index=True)
    container_id: Mapped[int | None] = mapped_column(ForeignKey("containers.id"), nullable=True)
    plate_number: Mapped[str] = mapped_column(String(30), index=True)
    driver_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), index=True)
    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    processing_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"), index=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    equipment_type: Mapped[str] = mapped_column(String(40), index=True)
    state: Mapped[str] = mapped_column(String(30), index=True)
    availability: Mapped[float] = mapped_column(Float, default=1.0)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    last_service_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EquipmentTelemetry(Base):
    __tablename__ = "equipment_telemetry"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temperature_c: Mapped[float] = mapped_column(Float)
    vibration_mm_s: Mapped[float] = mapped_column(Float)
    hydraulic_bar: Mapped[float] = mapped_column(Float)
    load_pct: Mapped[float] = mapped_column(Float)
    anomaly_score: Mapped[float] = mapped_column(Float, default=0)
    __table_args__ = (Index("ix_telemetry_equipment_time", "equipment_id", "recorded_at"),)


class ReeferReading(Base):
    __tablename__ = "reefer_readings"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    container_id: Mapped[int] = mapped_column(ForeignKey("containers.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    target_c: Mapped[float] = mapped_column(Float)
    actual_c: Mapped[float] = mapped_column(Float)
    power_on: Mapped[bool] = mapped_column(Boolean, default=True)
    door_open: Mapped[bool] = mapped_column(Boolean, default=False)
    alarm_state: Mapped[str] = mapped_column(String(30), default="normal", index=True)
    sensor_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    communication_ok: Mapped[bool] = mapped_column(Boolean, default=True)


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[int] = mapped_column(ForeignKey("terminals.id"), index=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="offline", index=True)
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fps: Mapped[float] = mapped_column(Float, default=0)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)


class CameraZone(Base):
    __tablename__ = "camera_zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    polygon_json: Mapped[str] = mapped_column(Text)
    rule_type: Mapped[str] = mapped_column(String(50), default="restricted_intrusion")
    severity: Mapped[str] = mapped_column(String(20), default="high")
    dwell_seconds: Mapped[float] = mapped_column(Float, default=0.2)
    cooldown_seconds: Mapped[float] = mapped_column(Float, default=5.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SafetyEvent(Base):
    __tablename__ = "safety_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("camera_zones.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    evidence_path: Mapped[str] = mapped_column(String(500))
    review_status: Mapped[str] = mapped_column(String(30), default="unreviewed", index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    source_event_id: Mapped[int | None] = mapped_column(ForeignKey("safety_events.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    incident_type: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(120), nullable=True)
    assigned_team: Mapped[str | None] = mapped_column(String(120), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reopened_count: Mapped[int] = mapped_column(Integer, default=0)
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IncidentNote(Base):
    __tablename__ = "incident_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WorkOrder(Base):
    __tablename__ = "work_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("equipment.id"), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    assigned_team: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checklist_json: Mapped[str] = mapped_column(Text, default="[]")
    completion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OperationalEvent(Base):
    __tablename__ = "operational_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    terminal_id: Mapped[int | None] = mapped_column(ForeignKey("terminals.id"), nullable=True, index=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(60), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    processing_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(80), default="api")
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class TwinSnapshot(Base):
    __tablename__ = "digital_twin_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    state_json: Mapped[str] = mapped_column(Text)
    event_count: Mapped[int] = mapped_column(Integer)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    scenario: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(30), default="created", index=True)
    speed_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    random_seed: Mapped[int] = mapped_column(Integer, default=20260719)
    simulated_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OCRJob(Base):
    __tablename__ = "ocr_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    source_path: Mapped[str] = mapped_column(String(500))
    crop_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enhanced_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_number: Mapped[str | None] = mapped_column(String(11), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float)
    validation_status: Mapped[str] = mapped_column(String(30), index=True)
    candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
