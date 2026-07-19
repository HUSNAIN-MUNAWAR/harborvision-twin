from __future__ import annotations

import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "sample" / "world-port-index-sample.csv"
ARCGIS_QUERY = "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/WPI_Ports2017/FeatureServer/0/query"
SOURCE_PAGE = "https://msi.nga.mil/Publications/WPI"

FIELDS = [
    "INDEX_NO",
    "PORT_NAME",
    "COUNTRY",
    "LATITUDE",
    "LONGITUDE",
    "HARBORSIZE",
    "HARBORTYPE",
    "SHELTER",
    "TIDE_RANGE",
    "CHAN_DEPTH",
    "CARGODEPTH",
    "MAX_VESSEL",
    "ETAMESSAGE",
    "PILOT_REQD",
    "PILOTAVAIL",
    "TUG_ASSIST",
    "CARGOWHARF",
    "COMM_VHF",
    "COMM_RAIL",
    "MED_FACIL",
    "PROVISIONS",
    "WATER",
    "FUEL_OIL",
    "DIESEL",
    "REPAIRCODE",
    "RAILWAY",
]

OUTPUT_FIELDS = [
    "wpi_number",
    "port_name",
    "country",
    "latitude",
    "longitude",
    "harbor_size",
    "harbor_type",
    "shelter",
    "tide_range_m",
    "channel_depth_code",
    "cargo_depth_code",
    "max_vessel_code",
    "eta_message",
    "pilot_required",
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
    "repair_code",
    "railway",
    "readiness_score",
]


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def yes(value: str) -> bool:
    return value.upper() == "Y"


def readiness(row: dict[str, str]) -> int:
    service_fields = [
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
    score = sum(8 for field in service_fields if yes(row[field]))
    if row["harbor_size"] == "L":
        score += 8
    if row["harbor_size"] == "M":
        score += 5
    if row["repair_code"] in {"A", "B", "C"}:
        score += 4
    if row["railway"]:
        score += 4
    return min(score, 100)


def fetch_features() -> list[dict[str, Any]]:
    params = {
        "where": "1=1",
        "outFields": ",".join(FIELDS),
        "returnGeometry": "false",
        "resultRecordCount": "4000",
        "f": "json",
    }
    url = f"{ARCGIS_QUERY}?{urllib.parse.urlencode(params)}"
    print(f"Downloading World Port Index features from {ARCGIS_QUERY}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return [feature["attributes"] for feature in payload.get("features", [])]


def transform(attributes: dict[str, Any]) -> dict[str, str]:
    row = {
        "wpi_number": clean(attributes.get("INDEX_NO")).removesuffix(".0"),
        "port_name": clean(attributes.get("PORT_NAME")),
        "country": clean(attributes.get("COUNTRY")),
        "latitude": clean(attributes.get("LATITUDE")),
        "longitude": clean(attributes.get("LONGITUDE")),
        "harbor_size": clean(attributes.get("HARBORSIZE")),
        "harbor_type": clean(attributes.get("HARBORTYPE")),
        "shelter": clean(attributes.get("SHELTER")),
        "tide_range_m": clean(attributes.get("TIDE_RANGE")),
        "channel_depth_code": clean(attributes.get("CHAN_DEPTH")),
        "cargo_depth_code": clean(attributes.get("CARGODEPTH")),
        "max_vessel_code": clean(attributes.get("MAX_VESSEL")),
        "eta_message": clean(attributes.get("ETAMESSAGE")),
        "pilot_required": clean(attributes.get("PILOT_REQD")),
        "pilot_available": clean(attributes.get("PILOTAVAIL")),
        "tug_assist": clean(attributes.get("TUG_ASSIST")),
        "cargo_wharf": clean(attributes.get("CARGOWHARF")),
        "vhf": clean(attributes.get("COMM_VHF")),
        "rail": clean(attributes.get("COMM_RAIL")),
        "medical": clean(attributes.get("MED_FACIL")),
        "provisions": clean(attributes.get("PROVISIONS")),
        "potable_water": clean(attributes.get("WATER")),
        "fuel_oil": clean(attributes.get("FUEL_OIL")),
        "diesel": clean(attributes.get("DIESEL")),
        "repair_code": clean(attributes.get("REPAIRCODE")),
        "railway": clean(attributes.get("RAILWAY")),
    }
    row["readiness_score"] = str(readiness(row))
    return row


def select_sample(rows: list[dict[str, str]], limit: int = 120) -> list[dict[str, str]]:
    valid = [
        row
        for row in rows
        if row["wpi_number"]
        and row["port_name"]
        and row["country"]
        and row["latitude"]
        and row["longitude"]
        and row["harbor_size"] in {"L", "M"}
    ]
    ranked = sorted(valid, key=lambda row: (-int(row["readiness_score"]), row["country"], row["port_name"]))
    sample = ranked[:limit]
    if len(sample) < limit:
        raise RuntimeError(f"Expected at least {limit} valid WPI records, got {len(sample)}")
    return sample


def main() -> None:
    rows = [transform(attributes) for attributes in fetch_features()]
    sample = select_sample(rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(sample)
    countries = sorted({row["country"] for row in sample})
    print(
        json.dumps(
            {
                "status": "passed",
                "source": SOURCE_PAGE,
                "download_source": ARCGIS_QUERY,
                "output": str(OUTPUT.relative_to(ROOT)),
                "records": len(sample),
                "countries": len(countries),
                "license": "Public domain; U.S. Government work under 17 U.S.C. §105",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
