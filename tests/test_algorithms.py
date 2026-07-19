from __future__ import annotations

from harborvision.algorithms import (
    can_transition_incident,
    congestion_score,
    make_container_number,
    point_in_polygon,
    rolling_z_scores,
    validate_container_number,
)
from harborvision.vision import CentroidTracker


def test_iso_6346_generation_and_validation():
    number = make_container_number("MSCU100000")
    assert number == "MSCU1000001"
    assert validate_container_number(number)["valid"] is True
    assert validate_container_number(number[:-1] + "9")["valid"] is False


def test_congestion_score_is_explainable_and_bounded():
    result = congestion_score(queue_length=24, avg_wait_minutes=38, open_lanes=3, yard_utilization=0.89, berth_utilization=0.75)
    assert 0 <= result["score"] <= 100
    assert result["level"] in {"high", "critical"}
    assert result["formula"].startswith("0.35")
    assert set(result["components"]) == {"lane_pressure", "wait_pressure", "yard_pressure", "berth_pressure"}


def test_incident_state_machine():
    assert can_transition_incident("open", "acknowledged")
    assert not can_transition_incident("open", "resolved")
    assert can_transition_incident("resolved", "open")


def test_polygon_geometry():
    polygon = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon((5, 5), polygon)
    assert not point_in_polygon((12, 5), polygon)


def test_rolling_z_score_detects_spike():
    values = [10, 10.2, 9.9, 10.1, 10.0, 10.2, 16.0]
    scores = rolling_z_scores(values, window=6)
    assert scores[-1] > 10


def test_centroid_tracker_preserves_track_identity():
    tracker = CentroidTracker(max_distance=60, max_missed=2)
    first = tracker.update([(10, 10, 30, 40)], 0.0)
    second = tracker.update([(25, 15, 30, 40)], 0.1)
    assert first[0].track_id == second[0].track_id == 1
    assert second[0].centroid == (40, 35)
