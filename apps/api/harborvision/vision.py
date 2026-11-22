from __future__ import annotations

import csv
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from .algorithms import point_in_polygon, validate_container_number
from .config import ROOT, settings
from .models import Camera, CameraZone, OCRJob, SafetyEvent


@dataclass
class Track:
    track_id: int
    centroid: tuple[int, int]
    bbox: tuple[int, int, int, int]
    first_seen: float
    last_seen: float
    missed: int = 0
    hits: int = 1
    history: list[tuple[int, int]] = field(default_factory=list)
    zone_entered_at: dict[int, float] = field(default_factory=dict)
    emitted_at: dict[int, float] = field(default_factory=dict)


class CentroidTracker:
    def __init__(self, max_distance: float = 80, max_missed: int = 8):
        self.max_distance = max_distance
        self.max_missed = max_missed
        self.next_id = 1
        self.tracks: dict[int, Track] = {}

    def update(self, boxes: list[tuple[int, int, int, int]], now: float) -> list[Track]:
        centroids = [(x + w // 2, y + h // 2) for x, y, w, h in boxes]
        unmatched = set(range(len(boxes)))
        for track in list(self.tracks.values()):
            if not unmatched:
                track.missed += 1
                continue
            best = min(unmatched, key=lambda i: math.dist(track.centroid, centroids[i]))
            distance = math.dist(track.centroid, centroids[best])
            if distance <= self.max_distance:
                track.history.append(track.centroid)
                track.history = track.history[-20:]
                track.centroid = centroids[best]
                track.bbox = boxes[best]
                track.last_seen = now
                track.missed = 0
                track.hits += 1
                unmatched.remove(best)
            else:
                track.missed += 1
        for index in unmatched:
            self.tracks[self.next_id] = Track(self.next_id, centroids[index], boxes[index], now, now, history=[centroids[index]])
            self.next_id += 1
        for track_id in [tid for tid, track in self.tracks.items() if track.missed > self.max_missed]:
            del self.tracks[track_id]
        return list(self.tracks.values())


def generate_sample_video(path: Path, width: int = 960, height: int = 540, frames: int = 150, fps: int = 15) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))  # type: ignore[attr-defined]
    for index in range(frames):
        frame = np.full((height, width, 3), (18, 32, 44), dtype=np.uint8)
        cv2.rectangle(frame, (80, 80), (880, 460), (45, 62, 72), 2)
        cv2.rectangle(frame, (560, 150), (860, 420), (32, 46, 55), -1)
        cv2.putText(frame, "RESTRICTED CRANE ENVELOPE", (575, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (60, 180, 230), 2)
        x = 40 + index * 5
        y = 270 + int(18 * math.sin(index / 8))
        cv2.rectangle(frame, (x, y), (x + 55, y + 90), (230, 180, 35), -1)
        cv2.circle(frame, (x + 27, y - 15), 17, (220, 190, 150), -1)
        cv2.putText(frame, f"FRAME {index:03d}", (30, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 220, 230), 2)
        writer.write(frame)
    writer.release()
    return path


def process_video(
    db: Session,
    organization_id: int,
    camera: Camera,
    zone: CameraZone,
    video_path: Path,
    annotated_output: Path | None = None,
    trace_output: Path | None = None,
) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    subtractor = cv2.createBackgroundSubtractorMOG2(history=80, varThreshold=35, detectShadows=False)
    tracker = CentroidTracker()
    polygon = json.loads(zone.polygon_json)
    evidence_dir = settings.storage_dir / "evidence"
    annotated_dir = settings.storage_dir / "annotated"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir.mkdir(parents=True, exist_ok=True)
    events = 0
    processed = 0
    started = time.perf_counter()
    latest_path = annotated_dir / f"{camera.code.lower()}-latest.jpg"
    annotated_writer = None
    trace_rows: list[dict[str, object]] = []
    if annotated_output is not None:
        annotated_output.parent.mkdir(parents=True, exist_ok=True)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        annotated_writer = cv2.VideoWriter(
            str(annotated_output),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )  # type: ignore[attr-defined]
        if not annotated_writer.isOpened():
            cap.release()
            raise RuntimeError(f"Cannot create annotated video {annotated_output}")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        processed += 1
        timestamp = processed / fps
        mask = subtractor.apply(frame)
        mask = cv2.medianBlur(mask, 5)
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: list[tuple[int, int, int, int]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if 800 <= area <= 25000:
                x, y, w, h = cv2.boundingRect(contour)
                boxes.append((x, y, w, h))
        tracks = tracker.update(boxes, timestamp)
        overlay = frame.copy()
        pts = np.array(polygon, dtype=np.int32)
        cv2.polylines(overlay, [pts], True, (40, 80, 255), 3)
        for track in tracks:
            x, y, w, h = track.bbox
            inside = point_in_polygon(track.centroid, polygon)
            color = (20, 40, 240) if inside else (40, 210, 120)
            cv2.rectangle(overlay, (x, y), (x + w, y + h), color, 2)
            cv2.circle(overlay, track.centroid, 5, color, -1)
            direction = "stationary"
            if track.history:
                dx = track.centroid[0] - track.history[0][0]
                dy = track.centroid[1] - track.history[0][1]
                if abs(dx) > abs(dy) and abs(dx) > 8:
                    direction = "east" if dx > 0 else "west"
                elif abs(dy) > 8:
                    direction = "south" if dy > 0 else "north"
            confirmed = track.hits >= 3
            event_emitted = False
            cv2.putText(overlay, f"T{track.track_id} {direction}", (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 2)
            if inside and confirmed:
                entered = track.zone_entered_at.setdefault(zone.id, timestamp)
                last_emitted = track.emitted_at.get(zone.id, -10_000)
                if timestamp - entered >= zone.dwell_seconds and timestamp - last_emitted >= zone.cooldown_seconds:
                    evidence_path = evidence_dir / f"intrusion-{camera.code}-{processed:05d}.jpg"
                    cv2.imwrite(str(evidence_path), overlay)
                    db.add(
                        SafetyEvent(
                            organization_id=organization_id,
                            camera_id=camera.id,
                            zone_id=zone.id,
                            event_type="restricted_zone_intrusion",
                            severity=zone.severity,
                            track_id=track.track_id,
                            confidence=0.92,
                            detected_at=datetime.now(UTC),
                            evidence_path=str(evidence_path.relative_to(ROOT)),
                            details_json=json.dumps(
                                {
                                    "frame": processed,
                                    "frame_timestamp_seconds": round(timestamp, 3),
                                    "centroid": track.centroid,
                                    "bbox": track.bbox,
                                    "dwell_seconds": round(timestamp - entered, 2),
                                    "direction": direction,
                                    "track_hits": track.hits,
                                    "rule": zone.rule_type,
                                    "zone": zone.name,
                                    "source": str(video_path.relative_to(ROOT)),
                                }
                            ),
                        )
                    )
                    track.emitted_at[zone.id] = timestamp
                    events += 1
                    event_emitted = True
            else:
                track.zone_entered_at.pop(zone.id, None)
            if trace_output is not None:
                trace_rows.append(
                    {
                        "frame": processed,
                        "timestamp_seconds": round(timestamp, 3),
                        "track_id": track.track_id,
                        "x": x,
                        "y": y,
                        "width": w,
                        "height": h,
                        "centroid_x": track.centroid[0],
                        "centroid_y": track.centroid[1],
                        "inside_zone": inside,
                        "confirmed": confirmed,
                        "direction": direction,
                        "event_emitted": event_emitted,
                    }
                )
        if annotated_writer is not None:
            annotated_writer.write(overlay)
        if processed % 10 == 0 or events:
            cv2.imwrite(str(latest_path), overlay)
    cap.release()
    if annotated_writer is not None:
        annotated_writer.release()
    if trace_output is not None:
        trace_output.parent.mkdir(parents=True, exist_ok=True)
        with trace_output.open("w", newline="", encoding="utf-8") as handle:
            fields = [
                "frame", "timestamp_seconds", "track_id", "x", "y", "width", "height",
                "centroid_x", "centroid_y", "inside_zone", "confirmed", "direction", "event_emitted",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(trace_rows)
    elapsed = time.perf_counter() - started
    camera.status = "online"
    camera.last_frame_at = datetime.now(UTC)
    camera.fps = processed / elapsed if elapsed else 0
    db.commit()
    return {
        "video": str(video_path.relative_to(ROOT)),
        "frames_processed": processed,
        "events_created": events,
        "processing_fps": round(processed / elapsed, 2) if elapsed else 0,
        "latest_annotated_frame": str(latest_path.relative_to(ROOT)),
        "annotated_output": str(annotated_output) if annotated_output else None,
        "trace_output": str(trace_output) if trace_output else None,
        "tracked_rows": len(trace_rows),
    }


def generate_container_image(number: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1100, 360), (174, 82, 34))
    draw = ImageDraw.Draw(image)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    small: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
        small = font
    draw.rectangle((30, 40, 1070, 300), outline=(245, 238, 210), width=8)
    draw.text((95, 95), number, fill=(250, 245, 220), font=font, stroke_width=2, stroke_fill=(20, 20, 20))
    draw.text((70, 315), "HARBORVISION SYNTHETIC OCR SAMPLE", fill=(245, 238, 210), font=small)
    image.save(path)
    return path


def _candidate_numbers(text: str) -> list[str]:
    cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
    candidates = []
    for match in re.finditer(r"[A-Z]{3}[UJZ][0-9]{7}", cleaned):
        candidates.append(match.group(0))
    if len(cleaned) >= 11:
        for start in range(len(cleaned) - 10):
            value = cleaned[start : start + 11]
            if re.match(r"^[A-Z]{3}[UJZ][0-9]{7}$", value):
                candidates.append(value)
    return list(dict.fromkeys(candidates))


def process_ocr(db: Session, organization_id: int, image_path: Path) -> dict:
    started = time.perf_counter()
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"Cannot read image {image_path}")
    height, width = image.shape[:2]
    # The local sample uses a configurable primary code region; excluding footer
    # text mirrors a gate-camera ROI and avoids unrelated signage.
    roi = image[int(height * 0.14) : int(height * 0.80), int(width * 0.04) : int(width * 0.98)]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ocr_dir = settings.storage_dir / "ocr"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    stem = f"ocr-{int(time.time() * 1000)}"
    crop_path = ocr_dir / f"{stem}-crop.png"
    enhanced_path = ocr_dir / f"{stem}-enhanced.png"
    cv2.imwrite(str(crop_path), roi)
    cv2.imwrite(str(enhanced_path), processed)
    config = "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    data = pytesseract.image_to_data(processed, config=config, output_type=pytesseract.Output.DICT)
    tokens = [token for token in data.get("text", []) if token.strip()]
    raw = " ".join(tokens)
    confidences = [float(c) for c in data.get("conf", []) if str(c).replace(".", "", 1).isdigit() and float(c) >= 0]
    candidates = _candidate_numbers(raw)
    ranked = []
    for candidate in candidates:
        validation = validate_container_number(candidate)
        ranked.append({"number": candidate, "valid": validation["valid"], "score": 1.0 if validation["valid"] else 0.45})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    selected = ranked[0]["number"] if ranked else None
    valid = validate_container_number(selected)["valid"] if selected else False
    confidence = (sum(confidences) / len(confidences) / 100) if confidences else 0.0
    job = OCRJob(
        organization_id=organization_id,
        source_path=str(image_path.relative_to(ROOT)),
        crop_path=str(crop_path.relative_to(ROOT)),
        enhanced_path=str(enhanced_path.relative_to(ROOT)),
        raw_text=raw,
        normalized_number=selected,
        confidence=round(confidence, 3),
        validation_status="valid" if valid else "review_required",
        candidates_json=json.dumps(ranked),
    )
    db.add(job)
    db.commit()
    return {
        "job_id": job.id,
        "raw_text": raw,
        "normalized_number": selected,
        "confidence": round(confidence, 3),
        "validation_status": job.validation_status,
        "candidates": ranked,
        "processing_ms": round((time.perf_counter() - started) * 1000, 1),
        "engine": {"name": "Tesseract", "adapter": "local_cpu", "external_api": False},
        "evidence": {"original": job.source_path, "crop": job.crop_path, "enhanced": job.enhanced_path},
        "preprocessing": ["grayscale", "CLAHE", "Gaussian blur", "Otsu threshold", "Tesseract whitelist", "ISO 6346 validation"],
    }
