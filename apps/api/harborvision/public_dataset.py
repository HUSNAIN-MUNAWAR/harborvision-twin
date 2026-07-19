from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ROOT

DATASET_SAMPLE = ROOT / "data" / "sample" / "world-port-index-sample.csv"
DATASET_TITLE = "World Port Index (Pub 150) processed smart-port sample"
DATASET_PUBLISHER = "National Geospatial-Intelligence Agency"
DATASET_SOURCE = "https://msi.nga.mil/Publications/WPI"
DATASET_DOWNLOAD_SOURCE = "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/WPI_Ports2017/FeatureServer/0/query"
DATASET_LICENSE = "Public domain; U.S. Government work under 17 U.S.C. §105"


@dataclass(frozen=True)
class PublicPort:
    wpi_number: str
    port_name: str
    country: str
    latitude: float
    longitude: float
    harbor_size: str
    harbor_type: str
    shelter: str
    tide_range_m: float | None
    channel_depth_code: str
    cargo_depth_code: str
    max_vessel_code: str
    eta_message: str
    pilot_required: str
    pilot_available: str
    tug_assist: str
    cargo_wharf: str
    vhf: str
    rail: str
    medical: str
    provisions: str
    potable_water: str
    fuel_oil: str
    diesel: str
    repair_code: str
    railway: str
    readiness_score: int


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _float(value: str | None) -> float | None:
    cleaned = _clean(value)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _yes(value: str) -> bool:
    return value.strip().upper() == "Y"


def _score(row: dict[str, str]) -> int:
    fields = [
        "eta_message",
        "pilot_available",
        "tug_assist",
        "cargo_wharf",
        "vhf",
        "rail",
        "medical",
        "provisions",
        "potable_water",
        "fuel_oil",
        "diesel",
    ]
    score = sum(8 for field in fields if _yes(row.get(field, "")))
    if row.get("harbor_size") == "L":
        score += 8
    if row.get("harbor_size") == "M":
        score += 5
    if _clean(row.get("repair_code")) in {"A", "B", "C"}:
        score += 4
    if _clean(row.get("railway")):
        score += 4
    return min(score, 100)


def load_public_ports(path: Path = DATASET_SAMPLE) -> list[PublicPort]:
    if not path.exists():
        return []
    rows: list[PublicPort] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row = {key: _clean(value) for key, value in raw.items()}
            rows.append(
                PublicPort(
                    wpi_number=row["wpi_number"],
                    port_name=row["port_name"],
                    country=row["country"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    harbor_size=row["harbor_size"],
                    harbor_type=row["harbor_type"],
                    shelter=row["shelter"],
                    tide_range_m=_float(row.get("tide_range_m")),
                    channel_depth_code=row["channel_depth_code"],
                    cargo_depth_code=row["cargo_depth_code"],
                    max_vessel_code=row["max_vessel_code"],
                    eta_message=row["eta_message"],
                    pilot_required=row["pilot_required"],
                    pilot_available=row["pilot_available"],
                    tug_assist=row["tug_assist"],
                    cargo_wharf=row["cargo_wharf"],
                    vhf=row["vhf"],
                    rail=row["rail"],
                    medical=row["medical"],
                    provisions=row["provisions"],
                    potable_water=row["potable_water"],
                    fuel_oil=row["fuel_oil"],
                    diesel=row["diesel"],
                    repair_code=row["repair_code"],
                    railway=row["railway"],
                    readiness_score=int(row.get("readiness_score") or _score(row)),
                )
            )
    return rows


def public_port_summary(limit: int = 24) -> dict[str, Any]:
    ports = load_public_ports()
    country_counts = Counter(port.country for port in ports)
    size_counts = Counter(port.harbor_size or "unknown" for port in ports)
    service_fields = {
        "eta_message": "ETA message",
        "pilot_available": "Pilotage available",
        "tug_assist": "Tug assistance",
        "cargo_wharf": "Cargo wharf",
        "vhf": "VHF communications",
        "rail": "Rail communications",
        "potable_water": "Potable water",
        "diesel": "Diesel",
    }
    service_coverage = {
        label: round(sum(1 for port in ports if _yes(getattr(port, field))) / len(ports) * 100, 1) if ports else 0
        for field, label in service_fields.items()
    }
    ranked = sorted(ports, key=lambda port: (-port.readiness_score, port.country, port.port_name))
    return {
        "dataset": {
            "title": DATASET_TITLE,
            "publisher": DATASET_PUBLISHER,
            "source": DATASET_SOURCE,
            "download_source": DATASET_DOWNLOAD_SOURCE,
            "license": DATASET_LICENSE,
            "sample_path": str(DATASET_SAMPLE.relative_to(ROOT)),
            "label": "Public-domain sample data, not customer or production terminal data",
        },
        "summary": {
            "sample_ports": len(ports),
            "countries": len(country_counts),
            "large_harbors": size_counts.get("L", 0),
            "medium_harbors": size_counts.get("M", 0),
            "average_readiness_score": round(sum(port.readiness_score for port in ports) / len(ports), 1) if ports else 0,
            "top_countries": [{"country": country, "ports": count} for country, count in country_counts.most_common(8)],
            "harbor_size_counts": dict(sorted(size_counts.items())),
            "service_coverage": service_coverage,
        },
        "ports": [
            {
                "wpi_number": port.wpi_number,
                "port_name": port.port_name,
                "country": port.country,
                "latitude": port.latitude,
                "longitude": port.longitude,
                "harbor_size": port.harbor_size,
                "harbor_type": port.harbor_type,
                "shelter": port.shelter,
                "channel_depth_code": port.channel_depth_code,
                "cargo_depth_code": port.cargo_depth_code,
                "pilot_available": port.pilot_available,
                "tug_assist": port.tug_assist,
                "cargo_wharf": port.cargo_wharf,
                "rail": port.rail,
                "diesel": port.diesel,
                "readiness_score": port.readiness_score,
            }
            for port in ranked[:limit]
        ],
    }
