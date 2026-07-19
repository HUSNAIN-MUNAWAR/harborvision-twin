from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Container, Incident, TruckVisit, VesselCall, YardSlot


def terminal_summary(db: Session, organization_id: int) -> dict:
    containers = db.scalar(select(func.count()).select_from(Container).where(Container.organization_id == organization_id)) or 0
    occupied = (
        db.scalar(
            select(func.count()).select_from(YardSlot).where(YardSlot.organization_id == organization_id, YardSlot.occupied.is_(True))
        )
        or 0
    )
    slots = db.scalar(select(func.count()).select_from(YardSlot).where(YardSlot.organization_id == organization_id)) or 0
    active_incidents = (
        db.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.organization_id == organization_id, Incident.status.not_in(["resolved", "dismissed"]))
        )
        or 0
    )
    vessel_calls = db.scalar(select(func.count()).select_from(VesselCall).where(VesselCall.organization_id == organization_id)) or 0
    truck_visits = db.scalar(select(func.count()).select_from(TruckVisit).where(TruckVisit.organization_id == organization_id)) or 0
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "containers": containers,
        "yard_occupancy_pct": round((occupied / slots * 100) if slots else 0, 1),
        "active_incidents": active_incidents,
        "vessel_calls": vessel_calls,
        "truck_visits": truck_visits,
    }


def build_daily_pdf(db: Session, organization_id: int) -> Path:
    summary = terminal_summary(db, organization_id)
    output = settings.storage_dir / "reports" / "daily-terminal-operations.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    story = [
        Paragraph("HarborVision Twin — Daily Terminal Operations Report", styles["Title"]),
        Spacer(1, 8),
        Paragraph(f"Generated: {summary['generated_at']}", styles["Normal"]),
        Spacer(1, 12),
    ]
    data = [
        ["Metric", "Value"],
        ["Containers in registry", str(summary["containers"])],
        ["Yard occupancy", f"{summary['yard_occupancy_pct']}%"],
        ["Active incidents", str(summary["active_incidents"])],
        ["Vessel calls", str(summary["vessel_calls"])],
        ["Truck visits", str(summary["truck_visits"])],
    ]
    table = Table(data, colWidths=[95 * mm, 60 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12324a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#8aa4b8")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#edf4f8")]),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 16),
            Paragraph("Engineering note", styles["Heading2"]),
            Paragraph(
                "All values in this report are calculated from the persisted HarborVision demonstration database. "
                "This local prototype is an operational engineering demonstrator and is not a certified terminal operating system.",
                styles["BodyText"],
            ),
        ]
    )
    doc.build(story)
    return output


def containers_csv(db: Session, organization_id: int) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["number", "status", "movement_type", "reefer", "hazardous", "weight_kg", "slot_id", "dwell_start"])
    for item in db.scalars(select(Container).where(Container.organization_id == organization_id).order_by(Container.number)):
        writer.writerow(
            [
                item.number,
                item.status,
                item.movement_type,
                item.is_reefer,
                item.is_hazardous,
                item.weight_kg,
                item.slot_id,
                item.dwell_start.isoformat(),
            ]
        )
    return output.getvalue()


REPORT_NAMES = {
    "daily-terminal-operations",
    "vessel-calls",
    "berth-utilization",
    "yard-occupancy",
    "container-dwell-exceptions",
    "gate-performance",
    "safety-incidents",
    "equipment-health",
    "maintenance-work-orders",
    "reefer-exceptions",
}


def operational_report_data(db: Session, organization_id: int, report_name: str) -> dict:
    from .domain_services import assess_reefer, equipment_risk_methods
    from .models import Berth, Equipment, EquipmentTelemetry, ReeferReading, SafetyEvent, WorkOrder, YardBlock

    if report_name not in REPORT_NAMES:
        raise ValueError(f"Unknown report: {report_name}")
    generated = datetime.now(UTC).isoformat()
    rows: list[dict] = []
    columns: list[str] = []
    if report_name == "daily-terminal-operations":
        summary = terminal_summary(db, organization_id)
        columns = ["metric", "value"]
        rows = [{"metric": key, "value": value} for key, value in summary.items() if key != "generated_at"]
    elif report_name == "vessel-calls":
        columns = ["vessel", "voyage", "status", "eta", "planned_start", "planned_end", "actual_moves", "target_moves"]
        for item in db.scalars(select(VesselCall).where(VesselCall.organization_id == organization_id).order_by(VesselCall.eta)):
            rows.append(
                {
                    "vessel": item.vessel_name,
                    "voyage": item.voyage_number,
                    "status": item.status,
                    "eta": item.eta.isoformat(),
                    "planned_start": item.planned_start.isoformat() if item.planned_start else None,
                    "planned_end": item.planned_end.isoformat() if item.planned_end else None,
                    "actual_moves": item.actual_moves,
                    "target_moves": item.target_moves,
                }
            )
    elif report_name == "berth-utilization":
        columns = ["berth", "length_m", "draft_limit_m", "planned_calls", "planned_hours"]
        for berth in db.scalars(select(Berth).where(Berth.organization_id == organization_id).order_by(Berth.code)):
            calls = list(
                db.scalars(select(VesselCall).where(VesselCall.organization_id == organization_id, VesselCall.berth_id == berth.id))
            )
            planned_hours = sum(
                max(0, (call.planned_end - call.planned_start).total_seconds() / 3600)
                for call in calls
                if call.planned_start and call.planned_end
            )
            rows.append(
                {
                    "berth": berth.code,
                    "length_m": berth.length_m,
                    "draft_limit_m": berth.draft_limit_m,
                    "planned_calls": len(calls),
                    "planned_hours": round(planned_hours, 2),
                }
            )
    elif report_name == "yard-occupancy":
        columns = ["block", "kind", "occupied", "capacity", "utilization_pct", "closed"]
        for block in db.scalars(select(YardBlock).where(YardBlock.organization_id == organization_id).order_by(YardBlock.code)):
            occupied = (
                db.scalar(select(func.count()).select_from(YardSlot).where(YardSlot.block_id == block.id, YardSlot.occupied.is_(True))) or 0
            )
            capacity = db.scalar(select(func.count()).select_from(YardSlot).where(YardSlot.block_id == block.id)) or 0
            rows.append(
                {
                    "block": block.code,
                    "kind": block.kind,
                    "occupied": occupied,
                    "capacity": capacity,
                    "utilization_pct": round(occupied / max(capacity, 1) * 100, 1),
                    "closed": block.is_closed,
                }
            )
    elif report_name == "container-dwell-exceptions":
        columns = ["container", "movement_type", "dwell_days", "reefer", "hazardous", "slot_id"]
        now = datetime.now(UTC).replace(tzinfo=None)
        containers = db.scalars(select(Container).where(Container.organization_id == organization_id).order_by(Container.dwell_start)).all()
        for item in containers:
            dwell = (now - item.dwell_start.replace(tzinfo=None)).total_seconds() / 86400
            if dwell >= 7:
                rows.append(
                    {
                        "container": item.number,
                        "movement_type": item.movement_type,
                        "dwell_days": round(dwell, 2),
                        "reefer": item.is_reefer,
                        "hazardous": item.is_hazardous,
                        "slot_id": item.slot_id,
                    }
                )
    elif report_name == "gate-performance":
        columns = ["plate", "status", "arrival", "wait_minutes", "service_minutes", "turnaround_minutes"]
        visits = db.scalars(
            select(TruckVisit).where(TruckVisit.organization_id == organization_id).order_by(TruckVisit.arrival_at.desc())
        ).all()
        for item in visits:
            rows.append(
                {
                    "plate": item.plate_number,
                    "status": item.status,
                    "arrival": item.arrival_at.isoformat(),
                    "wait_minutes": round((item.processing_start - item.arrival_at).total_seconds() / 60, 2)
                    if item.processing_start
                    else None,
                    "service_minutes": round((item.processing_end - item.processing_start).total_seconds() / 60, 2)
                    if item.processing_end and item.processing_start
                    else None,
                    "turnaround_minutes": round((item.exit_at - item.arrival_at).total_seconds() / 60, 2) if item.exit_at else None,
                }
            )
    elif report_name == "safety-incidents":
        columns = ["event_type", "severity", "camera_id", "track_id", "detected_at", "review_status", "evidence"]
        for item in db.scalars(
            select(SafetyEvent).where(SafetyEvent.organization_id == organization_id).order_by(SafetyEvent.detected_at.desc())
        ):
            rows.append(
                {
                    "event_type": item.event_type,
                    "severity": item.severity,
                    "camera_id": item.camera_id,
                    "track_id": item.track_id,
                    "detected_at": item.detected_at.isoformat(),
                    "review_status": item.review_status,
                    "evidence": item.evidence_path,
                }
            )
    elif report_name == "equipment-health":
        columns = ["equipment", "type", "state", "availability_pct", "risk", "risk_score", "explanation"]
        for item in db.scalars(select(Equipment).where(Equipment.organization_id == organization_id).order_by(Equipment.code)):
            telemetry = list(
                db.scalars(
                    select(EquipmentTelemetry)
                    .where(EquipmentTelemetry.equipment_id == item.id)
                    .order_by(EquipmentTelemetry.recorded_at.desc())
                    .limit(48)
                )
            )[::-1]
            risk = equipment_risk_methods(telemetry)
            rows.append(
                {
                    "equipment": item.code,
                    "type": item.equipment_type,
                    "state": item.state,
                    "availability_pct": round(item.availability * 100, 1),
                    "risk": risk["severity"],
                    "risk_score": risk["score"],
                    "explanation": " ".join(risk["explanations"]),
                }
            )
    elif report_name == "maintenance-work-orders":
        columns = ["title", "priority", "status", "equipment_id", "assigned_team", "due_at", "created_at"]
        for item in db.scalars(select(WorkOrder).where(WorkOrder.organization_id == organization_id).order_by(WorkOrder.created_at.desc())):
            rows.append(
                {
                    "title": item.title,
                    "priority": item.priority,
                    "status": item.status,
                    "equipment_id": item.equipment_id,
                    "assigned_team": item.assigned_team,
                    "due_at": item.due_at.isoformat() if item.due_at else None,
                    "created_at": item.created_at.isoformat(),
                }
            )
    elif report_name == "reefer-exceptions":
        columns = ["container", "state", "severity", "target_c", "actual_c", "duration_minutes", "suggested_action"]
        reefers = db.scalars(select(Container).where(Container.organization_id == organization_id, Container.is_reefer.is_(True))).all()
        for container in reefers:
            readings = list(
                db.scalars(
                    select(ReeferReading)
                    .where(ReeferReading.container_id == container.id)
                    .order_by(ReeferReading.recorded_at.desc())
                    .limit(48)
                )
            )[::-1]
            assessment = assess_reefer(readings)
            if assessment["state"] != "normal":
                rows.append(
                    {
                        "container": container.number,
                        "state": assessment["state"],
                        "severity": assessment["severity"],
                        "target_c": assessment.get("target_c"),
                        "actual_c": assessment.get("actual_c"),
                        "duration_minutes": assessment.get("duration_minutes"),
                        "suggested_action": assessment.get("suggested_action"),
                    }
                )
    return {
        "report": report_name,
        "generated_at": generated,
        "organization_id": organization_id,
        "demo_data": True,
        "filters": {},
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }


def operational_report_csv(data: dict) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data["columns"])
    writer.writeheader()
    writer.writerows(data["rows"])
    return output.getvalue()


def build_operational_pdf(db: Session, organization_id: int, report_name: str) -> Path:
    data = operational_report_data(db, organization_id, report_name)
    output = settings.storage_dir / "reports" / f"{report_name}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=12 * mm, leftMargin=12 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    story = [
        Paragraph(f"HarborVision Twin — {report_name.replace('-', ' ').title()}", styles["Title"]),
        Spacer(1, 6),
        Paragraph(f"Generated: {data['generated_at']} · Synthetic demonstration data", styles["Normal"]),
        Spacer(1, 10),
    ]
    columns = data["columns"]
    rows = data["rows"][:100]
    if rows:
        table_data = [columns] + [[str(row.get(column, ""))[:120] for column in columns] for row in rows]
        width = 185 * mm / max(len(columns), 1)
        table = Table(table_data, colWidths=[width] * len(columns), repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12324a")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#8aa4b8")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#edf4f8")]),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)
    else:
        story.append(Paragraph("No records matched the report criteria.", styles["BodyText"]))
    story.extend(
        [
            Spacer(1, 12),
            Paragraph(
                f"Rows: {data['row_count']}. Values are calculated from persisted records. This report is generated by an engineering demonstrator, not a certified terminal operating system.",
                styles["BodyText"],
            ),
        ]
    )
    doc.build(story)
    return output
