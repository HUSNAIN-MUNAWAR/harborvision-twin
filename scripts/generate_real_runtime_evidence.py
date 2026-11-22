"""Capture a reproducible artifact-backed run of HarborVision's actual vision path."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "animation" / "runtime-evidence"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def media_info(path: Path) -> dict[str, object]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open generated video: {path}")
    info = {
        "frames": int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": round(float(capture.get(cv2.CAP_PROP_FPS)), 3),
    }
    capture.release()
    if not info["frames"] or not info["width"] or not info["height"]:
        raise RuntimeError(f"Generated video has invalid media metadata: {info}")
    return info


def main() -> None:
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from harborvision.database import SessionLocal  # noqa: PLC0415
    from harborvision.models import Camera, CameraZone, Organization, SafetyEvent  # noqa: PLC0415
    from harborvision.seed import seed_database  # noqa: PLC0415
    from harborvision.vision import process_video  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    video_path = ROOT / "data" / "sample" / "restricted-zone-demo.mp4"
    if not video_path.is_file():
        raise RuntimeError(f"Seeded source video is missing: {video_path}")
    seed_database(reset=True)
    output_video = EVIDENCE / "harborvision-vision-runtime.mp4"
    trace_csv = EVIDENCE / "harborvision-vision-trace.csv"
    poster = EVIDENCE / "harborvision-vision-runtime-poster.jpg"
    with SessionLocal() as db:
        organization = db.scalar(select(Organization).order_by(Organization.id))
        camera = db.scalar(select(Camera).order_by(Camera.id))
        zone = db.scalar(select(CameraZone).order_by(CameraZone.id))
        if not organization or not camera or not zone:
            raise RuntimeError("Seed did not create the organization, camera, or safety zone.")
        result = process_video(
            db,
            organization.id,
            camera,
            zone,
            video_path,
            annotated_output=output_video,
            trace_output=trace_csv,
        )
        events = list(db.scalars(select(SafetyEvent).where(SafetyEvent.camera_id == camera.id).order_by(SafetyEvent.id)))
        event_rows = []
        for event in events:
            event_rows.append(
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "track_id": event.track_id,
                    "confidence": event.confidence,
                    "evidence_path": event.evidence_path,
                    "details": json.loads(event.details_json or "{}"),
                }
            )
        latest_frame = ROOT / result["latest_annotated_frame"]
        if latest_frame.is_file():
            shutil.copyfile(latest_frame, poster)
    result["annotated_output"] = str(output_video.relative_to(ROOT))
    result["trace_output"] = str(trace_csv.relative_to(ROOT))
    trace_rows = max(0, sum(1 for _ in trace_csv.open(encoding="utf-8")) - 1)
    summary = {
        "schema_version": "1.0",
        "evidence_kind": "real_local_runtime",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "path": str(video_path.relative_to(ROOT)),
            "sha256": sha256(video_path),
            "dataset_status": "repository-generated synthetic smoke media",
            "license_boundary": "original repository-generated asset; not field footage",
        },
        "runtime": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "opencv": cv2.__version__,
            "algorithm": "MOG2 background subtraction + morphology + contour area filter + nearest-centroid tracker",
            "decision_rule": "confirmed track inside configured polygon for dwell time with cooldown",
            "model_checkpoint": None,
            "external_endpoint": False,
            "result": result,
            "media": media_info(output_video),
            "trace_rows": trace_rows,
        },
        "events": event_rows,
        "artifacts": {
            "video": {"path": str(output_video.relative_to(ROOT)), "sha256": sha256(output_video)},
            "poster": {"path": str(poster.relative_to(ROOT)), "sha256": sha256(poster)},
            "trace": {"path": str(trace_csv.relative_to(ROOT)), "sha256": sha256(trace_csv)},
        },
        "ocr": {
            "status": "BLOCKED",
            "reason": "Tesseract executable is not installed on PATH on this host.",
            "reproduction": "Install Tesseract, then run PYTHONPATH=apps/api python scripts/ocr_evaluate.py.",
        },
        "claim_boundary": [
            "The video and trace are produced by the repository's executed motion-tracking pipeline.",
            "The pipeline detects motion-derived tracked objects; it is not a semantic person, vehicle, PPE, or certified safety detector.",
            "The source media and OCR evaluation are synthetic/local smoke evidence, not industrial field accuracy.",
        ],
    }
    target = EVIDENCE / "harborvision-vision-runtime-summary.json"
    target.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
