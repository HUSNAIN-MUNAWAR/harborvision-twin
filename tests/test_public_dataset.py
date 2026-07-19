from __future__ import annotations

from harborvision.public_dataset import load_public_ports, public_port_summary


def test_public_dataset_sample_loads():
    ports = load_public_ports()
    assert len(ports) == 120
    assert all(port.wpi_number for port in ports)
    assert all(port.port_name for port in ports)
    assert all(-90 <= port.latitude <= 90 for port in ports)
    assert all(-180 <= port.longitude <= 180 for port in ports)
    assert max(port.readiness_score for port in ports) <= 100


def test_public_dataset_endpoint_summary(client, director_headers):
    response = client.get("/api/v1/public-dataset/ports", headers=director_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["dataset"]["publisher"] == "National Geospatial-Intelligence Agency"
    assert data["summary"]["sample_ports"] == 120
    assert data["summary"]["countries"] >= 20
    assert data["ports"]


def test_public_dataset_summary_is_deterministic():
    summary = public_port_summary(limit=5)
    assert summary["summary"]["sample_ports"] == 120
    assert len(summary["ports"]) == 5
    assert summary["ports"] == sorted(summary["ports"], key=lambda port: (-port["readiness_score"], port["country"], port["port_name"]))
