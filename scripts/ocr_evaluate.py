from __future__ import annotations

import json

from harborvision.algorithms import validate_container_number
from harborvision.config import ROOT
from harborvision.database import SessionLocal
from harborvision.models import Container, Organization
from harborvision.vision import generate_container_image, process_ocr
from sqlalchemy import select


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, start=1):
        current = [index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def main() -> None:
    sample_dir = ROOT / "data" / "sample" / "ocr-evaluation"
    sample_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        organization = db.scalar(select(Organization).order_by(Organization.id))
        if not organization:
            raise RuntimeError("Seed the database before OCR evaluation")
        numbers = list(
            db.scalars(select(Container.number).where(Container.organization_id == organization.id).order_by(Container.number).limit(6))
        )
        if not numbers:
            raise RuntimeError("No seeded containers are available")
        rows = []
        for number in numbers:
            image_path = generate_container_image(number, sample_dir / f"{number}.png")
            result = process_ocr(db, organization.id, image_path)
            predicted = result.get("normalized_number") or ""
            rows.append(
                {
                    "expected": number,
                    "predicted": predicted,
                    "exact_match": predicted == number,
                    "character_accuracy": round(1 - edit_distance(number, predicted) / max(len(number), len(predicted), 1), 4),
                    "valid_id": bool(predicted and validate_container_number(predicted)["valid"]),
                    "confidence": result["confidence"],
                    "processing_ms": result["processing_ms"],
                    "review_required": result["validation_status"] != "valid",
                }
            )
    count = len(rows)
    summary = {
        "dataset": "deterministic synthetic HarborVision samples",
        "samples": count,
        "exact_match_accuracy": round(sum(row["exact_match"] for row in rows) / count, 4),
        "character_accuracy": round(sum(row["character_accuracy"] for row in rows) / count, 4),
        "valid_id_recovery_rate": round(sum(row["valid_id"] for row in rows) / count, 4),
        "average_confidence": round(sum(row["confidence"] for row in rows) / count, 4),
        "average_latency_ms": round(sum(row["processing_ms"] for row in rows) / count, 2),
        "review_required_rate": round(sum(row["review_required"] for row in rows) / count, 4),
        "warning": "Synthetic local results are not evidence of industrial field accuracy.",
        "results": rows,
    }
    target = ROOT / "docs" / "ocr-evaluation-results.json"
    target.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
