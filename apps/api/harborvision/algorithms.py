from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean, pstdev

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Container, EquipmentTelemetry, GateLane, TruckVisit, YardBlock, YardSlot

ISO6346_RE = re.compile(r"^[A-Z]{3}[UJZ][0-9]{7}$")
LETTER_VALUES = {
    "A": 10,
    "B": 12,
    "C": 13,
    "D": 14,
    "E": 15,
    "F": 16,
    "G": 17,
    "H": 18,
    "I": 19,
    "J": 20,
    "K": 21,
    "L": 23,
    "M": 24,
    "N": 25,
    "O": 26,
    "P": 27,
    "Q": 28,
    "R": 29,
    "S": 30,
    "T": 31,
    "U": 32,
    "V": 34,
    "W": 35,
    "X": 36,
    "Y": 37,
    "Z": 38,
}


def iso6346_check_digit(first_ten: str) -> int:
    value = first_ten.strip().upper()
    if len(value) != 10 or not re.match(r"^[A-Z]{4}[0-9]{6}$", value):
        raise ValueError("Container prefix must be four letters followed by six digits")
    total = 0
    for position, char in enumerate(value):
        numeric = LETTER_VALUES[char] if char.isalpha() else int(char)
        total += numeric * (2**position)
    remainder = total % 11
    return 0 if remainder == 10 else remainder


def make_container_number(prefix_and_serial: str) -> str:
    base = prefix_and_serial.upper()
    return f"{base}{iso6346_check_digit(base)}"


def validate_container_number(number: str) -> dict:
    normalized = re.sub(r"[^A-Z0-9]", "", number.upper())
    structure_valid = bool(ISO6346_RE.fullmatch(normalized))
    expected = None
    valid = False
    if structure_valid:
        expected = iso6346_check_digit(normalized[:10])
        valid = expected == int(normalized[-1])
    return {
        "number": normalized,
        "structure_valid": structure_valid,
        "expected_check_digit": expected,
        "valid": valid,
    }


def berth_conflicts(db: Session, organization_id: int, berth_id: int, start: datetime, end: datetime, exclude_id: int | None = None):
    from .models import VesselCall

    query = select(VesselCall).where(
        VesselCall.organization_id == organization_id,
        VesselCall.berth_id == berth_id,
        VesselCall.planned_start.is_not(None),
        VesselCall.planned_end.is_not(None),
        VesselCall.planned_start < end,
        VesselCall.planned_end > start,
    )
    if exclude_id:
        query = query.where(VesselCall.id != exclude_id)
    return list(db.scalars(query))


@dataclass
class SlotRecommendation:
    slot_id: int
    block_code: str
    bay: int
    row: int
    tier: int
    score: float
    explanation: list[str]


def recommend_yard_slot(db: Session, organization_id: int, container: Container, limit: int = 5) -> list[SlotRecommendation]:
    rows = db.execute(
        select(YardSlot, YardBlock)
        .join(YardBlock, YardSlot.block_id == YardBlock.id)
        .where(
            YardSlot.organization_id == organization_id,
            YardSlot.occupied.is_(False),
            YardBlock.organization_id == organization_id,
        )
    ).all()
    recommendations: list[SlotRecommendation] = []
    for slot, block in rows:
        explanation: list[str] = []
        score = 100.0
        now = datetime.now(UTC)
        if block.is_closed:
            continue
        if slot.reserved_until:
            reserved = slot.reserved_until if slot.reserved_until.tzinfo else slot.reserved_until.replace(tzinfo=UTC)
            if reserved > now:
                continue
        if container.weight_kg > slot.max_weight_kg:
            continue
        if block.allocation not in {"mixed", container.movement_type}:
            continue
        if container.is_reefer:
            if block.kind == "reefer":
                score += 50
                explanation.append("reefer-compatible powered block")
            else:
                score -= 1000
                explanation.append("rejected: reefer container requires reefer block")
        elif block.kind == "reefer":
            continue
        if container.is_hazardous:
            if block.kind == "hazardous":
                score += 55
                explanation.append("hazardous segregation satisfied")
            else:
                score -= 1000
                explanation.append("rejected: hazardous segregation required")
        elif block.kind == "hazardous":
            continue
        if container.movement_type == "export":
            score += max(0, 20 - block.x / 50)
            explanation.append("export retrieval distance considered")
        else:
            score += max(0, 12 - abs(block.y - 360) / 35)
            explanation.append("gate/berth travel distance considered")
        score -= slot.tier * 6
        score += min(20, max(0, container.retrieval_priority) / 5) if slot.tier == 1 else 0
        if container.expected_retrieval_at:
            eta = container.expected_retrieval_at
            eta = eta if eta.tzinfo else eta.replace(tzinfo=UTC)
            hours = max(0.0, (eta - now).total_seconds() / 3600)
            urgency = max(0.0, 24 - hours) / 24
            score += urgency * max(0, 18 - slot.tier * 5)
            explanation.append(f"retrieval horizon {hours:.1f} hours")
        if slot.tier == 1:
            explanation.append("ground-tier placement reduces rehandles")
        elif slot.tier > 2:
            explanation.append("higher tier increases rehandle risk")
        occupied = (
            db.scalar(select(func.count()).select_from(YardSlot).where(YardSlot.block_id == block.id, YardSlot.occupied.is_(True))) or 0
        )
        utilization = occupied / max(block.capacity, 1)
        score -= utilization * 45
        explanation.append(f"block utilization {utilization:.0%}")
        if score > -500:
            recommendations.append(SlotRecommendation(slot.id, block.code, slot.bay, slot.row, slot.tier, round(score, 2), explanation))
    return sorted(recommendations, key=lambda item: item.score, reverse=True)[:limit]


def congestion_score(
    queue_length: int, avg_wait_minutes: float, open_lanes: int, yard_utilization: float, berth_utilization: float
) -> dict:
    lane_pressure = min(1.0, queue_length / max(open_lanes * 8, 1))
    wait_pressure = min(1.0, avg_wait_minutes / 45.0)
    yard_pressure = min(1.0, max(0.0, (yard_utilization - 0.55) / 0.4))
    berth_pressure = min(1.0, berth_utilization)
    score = 100 * (0.35 * lane_pressure + 0.30 * wait_pressure + 0.20 * yard_pressure + 0.15 * berth_pressure)
    level = "critical" if score >= 75 else "high" if score >= 55 else "moderate" if score >= 30 else "normal"
    return {
        "score": round(score, 1),
        "level": level,
        "components": {
            "lane_pressure": round(lane_pressure, 3),
            "wait_pressure": round(wait_pressure, 3),
            "yard_pressure": round(yard_pressure, 3),
            "berth_pressure": round(berth_pressure, 3),
        },
        "formula": "0.35*lane + 0.30*wait + 0.20*yard + 0.15*berth",
    }


def rolling_z_scores(values: Sequence[float], window: int = 12) -> list[float]:
    scores: list[float] = []
    for index, value in enumerate(values):
        history = values[max(0, index - window) : index]
        if len(history) < 4:
            scores.append(0.0)
            continue
        deviation = pstdev(history)
        scores.append(0.0 if deviation < 1e-9 else (value - mean(history)) / deviation)
    return scores


def equipment_risk(telemetry: Iterable[EquipmentTelemetry]) -> dict:
    rows = list(telemetry)
    if not rows:
        return {"score": 0, "severity": "normal", "explanation": "No telemetry"}
    temp_scores = rolling_z_scores([r.temperature_c for r in rows])
    vibration_scores = rolling_z_scores([r.vibration_mm_s for r in rows])
    trend = 0.0
    if len(rows) >= 6:
        trend = rows[-1].temperature_c - rows[-6].temperature_c
    score = max(abs(temp_scores[-1]), abs(vibration_scores[-1])) + max(0, trend / 4)
    severity = "critical" if score >= 4 else "high" if score >= 3 else "watch" if score >= 2 else "normal"
    return {
        "score": round(score, 3),
        "severity": severity,
        "metric": "temperature/vibration",
        "explanation": f"Latest rolling deviation {max(abs(temp_scores[-1]), abs(vibration_scores[-1])):.2f}σ; six-reading temperature trend {trend:+.2f}°C",
        "suggested_action": "Inspect lubrication, cooling and load cycle" if severity != "normal" else "Continue monitoring",
    }


INCIDENT_TRANSITIONS = {
    "open": {"acknowledged", "dismissed"},
    "acknowledged": {"investigating", "dismissed"},
    "investigating": {"action_required", "resolved", "dismissed"},
    "action_required": {"investigating", "resolved"},
    "resolved": {"open"},
    "dismissed": {"open"},
}


def can_transition_incident(current: str, target: str) -> bool:
    return target in INCIDENT_TRANSITIONS.get(current, set())


def point_in_polygon(point: tuple[float, float], polygon: Sequence[Sequence[float]]) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def summarize_gate(db: Session, organization_id: int) -> dict:
    rows = list(db.scalars(select(TruckVisit).where(TruckVisit.organization_id == organization_id)))
    lanes = list(db.scalars(select(GateLane).where(GateLane.organization_id == organization_id)))
    queue = [r for r in rows if r.status in {"queued", "processing"}]
    waits = []
    service = []
    for row in rows:
        if row.processing_start:
            waits.append((row.processing_start - row.arrival_at).total_seconds() / 60)
        if row.processing_end and row.processing_start:
            service.append((row.processing_end - row.processing_start).total_seconds() / 60)
    return {
        "queue_length": len(queue),
        "average_wait_minutes": round(mean(waits), 1) if waits else 0,
        "average_service_minutes": round(mean(service), 1) if service else 0,
        "open_lanes": sum(1 for lane in lanes if lane.is_open),
        "closed_lanes": sum(1 for lane in lanes if not lane.is_open),
        "processed": sum(1 for r in rows if r.status == "completed"),
    }
