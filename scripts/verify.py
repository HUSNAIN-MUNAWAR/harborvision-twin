from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import cv2
import pytesseract
from fastapi.testclient import TestClient
from harborvision.config import ROOT
from harborvision.main import app
from harborvision.seed import seed_database


def progress(message: str) -> None:
    print(f"[verify] {message}", file=sys.stderr, flush=True)


def timed(client: TestClient, method: str, path: str, **kwargs: Any):
    started = time.perf_counter()
    response = getattr(client, method)(path, **kwargs)
    return response, round((time.perf_counter() - started) * 1000, 2)


def checked(client: TestClient, method: str, path: str, checks: dict[str, Any], name: str, **kwargs: Any):
    response, elapsed = timed(client, method, path, **kwargs)
    response.raise_for_status()
    progress(f"{name}: {response.status_code} in {elapsed} ms")
    checks[name] = {
        "status": response.status_code,
        "latency_ms": elapsed,
        "bytes": len(response.content),
    }
    return response


def main() -> None:
    try:
        tesseract_version = str(pytesseract.get_tesseract_version()).splitlines()[0]
    except pytesseract.pytesseract.TesseractNotFoundError:
        tesseract_version = None

    output: dict[str, Any] = {
        "verification_time": datetime.now(UTC).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "node": subprocess.run(["node", "--version"], capture_output=True, text=True, check=False).stdout.strip(),
            "tesseract": tesseract_version,
            "opencv": cv2.__version__,
            "docker_available": shutil.which("docker") is not None,
        },
        "commands": [],
        "checks": {},
        "warnings": [],
        "limitations": [],
    }
    progress("resetting and seeding deterministic database")
    seed_result = seed_database(reset=True)
    progress("seed complete")
    output["commands"].append(
        {
            "command": "PYTHONPATH=apps/api python -m harborvision.seed",
            "result": "passed",
            "summary": seed_result,
        }
    )

    progress("starting integrated API verification")
    with TestClient(app) as client:
        invalid = client.post(
            "/api/v1/auth/login",
            json={"email": "director@harborvision.local", "password": "not-the-password"},
        )
        output["checks"]["invalid_login"] = {"status": invalid.status_code, "passed": invalid.status_code == 401}

        login = checked(
            client,
            "post",
            "/api/v1/auth/login",
            output["checks"],
            "login",
            json={"email": "director@harborvision.local", "password": "HarborVision!2026"},
        )
        login_data = login.json()
        headers = {"Authorization": f"Bearer {login_data['access_token']}"}
        refresh_token = login_data["refresh_token"]

        health = checked(client, "get", "/api/v1/health/ready", output["checks"], "readiness", headers=headers)
        output["checks"]["readiness"]["components"] = health.json().get("components")
        dashboard = checked(client, "get", "/api/v1/dashboard", output["checks"], "dashboard", headers=headers)
        output["checks"]["dashboard"]["kpis"] = dashboard.json()["kpis"]
        checked(client, "get", "/api/v1/containers?q=CMAU&limit=20", output["checks"], "container_search", headers=headers)
        twin = checked(client, "get", "/api/v1/digital-twin/state", output["checks"], "digital_twin", headers=headers)
        output["checks"]["digital_twin"]["mode"] = twin.json()["mode"]

        end = datetime.now(UTC) + timedelta(hours=1)
        start = end - timedelta(hours=12)
        playback = checked(
            client,
            "get",
            "/api/v1/digital-twin/playback",
            output["checks"],
            "historical_playback",
            headers=headers,
            params={"start": start.isoformat(), "end": end.isoformat(), "limit": 500},
        )
        output["checks"]["historical_playback"].update(
            {
                "event_count": playback.json()["event_count"],
                "snapshot": playback.json()["snapshot"],
                "reconstruction": playback.json()["reconstruction"],
            }
        )

        containers = client.get("/api/v1/containers?limit=1", headers=headers).json()["items"]
        container_id = containers[0]["id"]
        placement = checked(
            client,
            "get",
            f"/api/v1/containers/{container_id}/placement-analysis?limit=10",
            output["checks"],
            "yard_placement_analysis",
            headers=headers,
        )
        output["checks"]["yard_placement_analysis"].update(
            {
                "candidate_count": len(placement.json()["recommendations"]),
                "rejected_sample_count": len(placement.json()["rejected_candidates"]),
                "method": placement.json()["method"],
            }
        )

        gate = checked(client, "get", "/api/v1/gates/overview", output["checks"], "gate_overview", headers=headers)
        visit_id = gate.json()["visits"][0]["id"]
        visit = checked(
            client,
            "get",
            f"/api/v1/gates/visits/{visit_id}",
            output["checks"],
            "truck_visit_timeline",
            headers=headers,
        )
        output["checks"]["truck_visit_timeline"]["stage_count"] = len(visit.json()["timeline"])

        analytics = checked(client, "get", "/api/v1/analytics/kpis", output["checks"], "analytics", headers=headers)
        output["checks"]["analytics"]["source"] = analytics.json()["source"]
        public_dataset = checked(
            client,
            "get",
            "/api/v1/public-dataset/ports?limit=10",
            output["checks"],
            "public_dataset",
            headers=headers,
        )
        output["checks"]["public_dataset"].update(
            {
                "sample_ports": public_dataset.json()["summary"]["sample_ports"],
                "countries": public_dataset.json()["summary"]["countries"],
                "license": public_dataset.json()["dataset"]["license"],
            }
        )

        simulation_create = checked(
            client,
            "post",
            "/api/v1/simulation/runs",
            output["checks"],
            "simulation_create",
            headers=headers,
            json={"scenario": "equipment_anomaly", "speed_multiplier": 10, "random_seed": 20260719},
        )
        run_id = simulation_create.json()["id"]
        checked(client, "post", f"/api/v1/simulation/runs/{run_id}/start", output["checks"], "simulation_start", headers=headers)
        simulation = checked(
            client,
            "post",
            f"/api/v1/simulation/runs/{run_id}/advance",
            output["checks"],
            "simulation_advance",
            headers=headers,
        )
        output["checks"]["simulation_advance"].update(
            {"state": simulation.json()["status"], "events_created": simulation.json()["event_count"]}
        )

        if tesseract_version:
            ocr = checked(client, "post", "/api/v1/ocr/process-sample", output["checks"], "ocr", headers=headers)
            output["checks"]["ocr"].update(
                {
                    "normalized_number": ocr.json()["normalized_number"],
                    "confidence": ocr.json()["confidence"],
                    "validation_status": ocr.json()["validation_status"],
                    "processing_ms": ocr.json()["processing_ms"],
                    "evidence": ocr.json()["evidence"],
                }
            )
        else:
            output["checks"]["ocr"] = {"passed": None, "skipped": True, "reason": "Tesseract OCR binary is not installed on PATH."}
            output["limitations"].append("OCR verification was skipped because Tesseract OCR is not installed on PATH.")

        vision = checked(client, "post", "/api/v1/vision/process-sample", output["checks"], "vision", headers=headers)
        output["checks"]["vision"].update(vision.json())
        safety = client.get("/api/v1/safety-events", headers=headers).json()
        output["checks"]["persisted_safety_event"] = {
            "passed": bool(safety),
            "count": len(safety),
            "latest": safety[0] if safety else None,
        }

        for report_name in ["daily-terminal-operations", "gate-performance", "equipment-health", "reefer-exceptions"]:
            report = checked(
                client,
                "get",
                f"/api/v1/reports/{report_name}/pdf",
                output["checks"],
                f"report_{report_name}",
                headers=headers,
            )
            output["checks"][f"report_{report_name}"]["pdf_signature"] = report.content[:4].decode("ascii", errors="replace")

        header_probe = client.get("/api/v1/dashboard", headers=headers)
        output["checks"]["security_headers"] = {
            "passed": all(
                name in header_probe.headers
                for name in ["x-request-id", "x-content-type-options", "x-frame-options", "content-security-policy"]
            ),
            "values": {
                name: header_probe.headers.get(name)
                for name in ["x-request-id", "x-content-type-options", "x-frame-options", "referrer-policy"]
            },
        }

        logout = client.post("/api/v1/auth/logout", headers=headers, json={"refresh_token": refresh_token})
        replay = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        output["checks"]["logout_revocation"] = {
            "logout_status": logout.status_code,
            "refresh_replay_status": replay.status_code,
            "passed": logout.status_code == 200 and replay.status_code == 401,
        }

    progress("API verification complete; running data integrity")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "apps" / "api")
    integrity = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "data_integrity.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output["checks"]["data_integrity"] = {
        "passed": integrity.returncode == 0,
        "result": json.loads(integrity.stdout) if integrity.stdout.strip().startswith("{") else integrity.stdout.strip(),
    }
    if integrity.returncode:
        raise RuntimeError(integrity.stderr or integrity.stdout)

    output["checks"]["web_assets"] = {
        "html_bytes": (ROOT / "apps" / "web" / "index.html").stat().st_size,
        "javascript_bytes": (ROOT / "apps" / "web" / "app.js").stat().st_size,
        "css_bytes": (ROOT / "apps" / "web" / "styles.css").stat().st_size,
    }
    if not output["environment"]["docker_available"]:
        output["limitations"].append("Docker commands cannot run because no Docker binary is installed on the verification host.")
    output["limitations"].extend(
        [
            "PostgreSQL/PostGIS, Redis, and MinIO runtime behavior is not claimed from the SQLite verification run.",
            "The web console is standards-based JavaScript rather than Next.js.",
            "Vision verification covers tracked motion and polygon rules, not semantic person, vehicle, PPE, or certified safety detection.",
            "OCR results use generated samples and are not industrial field-accuracy evidence.",
            "The worker is a heartbeat/process-separation baseline rather than a distributed queue with a dead-letter service.",
        ]
    )
    progress("writing verification evidence")
    target = ROOT / "docs" / "verification-results.json"
    target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
