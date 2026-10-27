"""Independent analytic paths test saved-study alignment, not forecast skill."""

import copy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from geographiclib.geodesic import Geodesic

from packages.domain.models import ComparisonRequest, MissionConfig, digest
from packages.flight.comparison import compare_runs
from services.api.main import create_app
from services.api.storage import Record

START = datetime(2026, 10, 27, 12, tzinfo=UTC)


def run(*, start=START, lon=9.0, height=12500.0, duration=100.0, coordinates=None):
    config = MissionConfig().model_dump(mode="json")
    config["name"] = "Explicit analytic comparison fixture"
    config["launch"]["start_utc"] = start.isoformat()
    config["flight"].update(
        initial_geometric_m=height, target_geometric_m=height, float_duration_hours=duration / 3600
    )
    coordinates = coordinates or [(0, 45.0, lon), (duration, 45.0, lon)]
    samples = [
        {
            "elapsed_s": float(t),
            "time_utc": (start + timedelta(seconds=t)).isoformat(),
            "latitude_deg": lat,
            "longitude_deg": x,
            "geometric_msl_m": height,
        }
        for t, lat, x in coordinates
    ]
    config["launch"].update(latitude_deg=coordinates[0][1], longitude_deg=coordinates[0][2])
    ident, revision = str(uuid4()), str(uuid4())
    output = {"samples": samples, "quality": "modeled_uncalibrated", "distance_m": 0, "duration_s": duration}
    manifest = {
        "simulation_id": ident,
        "revision_id": revision,
        "mission_id": config["id"],
        "created_utc": START.isoformat(),
        "config": config,
        "config_sha256": digest(config),
        "output_sha256": digest(output),
        "weather": {"provider": "SYNTHETIC", "origin": "analytic_test_fixture"},
    }
    manifest["sha256"] = digest(manifest)
    return {
        "id": ident,
        "name": config["name"],
        "revision_id": revision,
        "created_utc": manifest["created_utc"],
        "operating_mode": "DEMO",
        "weather_provider": "SYNTHETIC",
        "manifest": manifest,
        **output,
    }


def request(a, b, **kw):
    return ComparisonRequest(reference_id=a["id"], candidate_id=b["id"], **kw)


def test_stationary_separation_and_height_difference_against_geographiclib():
    a, b = run(), run(lon=9.01, height=13500)
    result = compare_runs(a, b, request(a, b, sample_count=21))
    expected = Geodesic.WGS84.Inverse(45, 9, 45, 9.01)["s12"]
    for key in (
        "maximum_sampled_separation_m",
        "mean_sampled_separation_m",
        "shared_window_end_separation_m",
    ):
        assert result["metrics"][key] == pytest.approx(expected, abs=1e-7)
    assert result["metrics"]["maximum_absolute_sampled_height_difference_m"] == 1000
    assert result["duration_s"] == 100
    assert any(row["field"] == "flight.target_geometric_m" for row in result["configuration_differences"])
    assert (
        digest({k: v for k, v in result.items() if k != "comparison_sha256"}) == result["comparison_sha256"]
    )


def test_elapsed_and_utc_alignment_have_distinct_horizons_and_time_pairs():
    a, b = run(), run(start=START + timedelta(seconds=60))
    elapsed = compare_runs(a, b, request(a, b, alignment="elapsed", sample_count=3))
    utc = compare_runs(a, b, request(a, b, alignment="utc", sample_count=3))
    assert elapsed["duration_s"] == 100 and utc["duration_s"] == 40
    assert elapsed["points"][0]["reference"]["time_utc"] != elapsed["points"][0]["candidate"]["time_utc"]
    for row in utc["points"]:
        assert row["reference"]["time_utc"] == row["candidate"]["time_utc"]
    assert utc["points"][0]["reference"]["elapsed_s"] == 60
    assert utc["points"][0]["candidate"]["elapsed_s"] == 0
    b = run(start=START + timedelta(seconds=200))
    with pytest.raises(ValueError, match="no positive shared"):
        compare_runs(a, b, request(a, b, alignment="utc"))


def test_geodesic_interpolation_takes_short_dateline_path_and_different_cadences_agree():
    a = run(coordinates=[(0, 0, 179.9), (100, 0, -179.9)])
    b = run(coordinates=[(0, 0, 179.9), (50, 0, 180), (100, 0, -179.9)])
    result = compare_runs(a, b, request(a, b, sample_count=51))
    assert result["metrics"]["maximum_sampled_separation_m"] < 1e-6
    assert all(abs(row["reference"]["longitude_deg"]) > 179.89 for row in result["points"])
    assert result["points"][25]["reference"]["longitude_deg"] == pytest.approx(180)


def test_shared_window_does_not_extrapolate_longer_study_or_lose_fractional_seconds():
    a, b = run(duration=100.123456), run(start=START + timedelta(seconds=0.123456), duration=50.654321)
    result = compare_runs(a, b, request(a, b, alignment="utc", sample_count=13))
    assert result["duration_s"] == pytest.approx(50.654321, abs=1e-9)
    assert result["points"][-1]["candidate"]["elapsed_s"] == pytest.approx(50.654321)


@pytest.mark.parametrize("damage", ["duplicate_time", "nonfinite", "time_mismatch", "naive_time"])
def test_invalid_saved_axes_are_rejected(damage):
    a, b = run(), run()
    if damage == "duplicate_time":
        b["samples"][1]["elapsed_s"] = 0
    elif damage == "nonfinite":
        b["samples"][0]["latitude_deg"] = float("nan")
    elif damage == "time_mismatch":
        b["samples"][0]["time_utc"] = (START + timedelta(seconds=2)).isoformat()
    else:
        b["manifest"]["config"]["launch"]["start_utc"] = START.replace(tzinfo=None).isoformat()
    with pytest.raises(ValueError):
        compare_runs(a, b, request(a, b))


def test_comparison_api_verifies_sources_and_enforces_bounded_request(tmp_path):
    a, b = run(), run(lon=9.01, height=13500)
    app = create_app(tmp_path, seed=False)
    with TestClient(app) as client:
        with app.state.sessions() as session:
            for record in (a, b):
                session.add(Record(id=record["id"], kind="simulation", payload=record))
            session.commit()
        body = request(a, b, sample_count=11).model_dump(mode="json")
        result = client.post("/api/simulations/compare", json=body)
        assert result.status_code == 200, result.text
        data = result.json()
        assert len(data["points"]) == 11
        assert data["sources"][0]["output_sha256"] == a["manifest"]["output_sha256"]
        assert data["code"]["scientific_source_sha256"]
        assert (
            digest({k: v for k, v in data.items() if k != "comparison_sha256"}) == data["comparison_sha256"]
        )
        assert client.post("/api/simulations/compare", json={**body, "sample_count": 1002}).status_code == 422
        assert (
            client.post("/api/simulations/compare", json={**body, "candidate_id": a["id"]}).status_code == 422
        )
        with app.state.sessions() as session:
            row = session.get(Record, b["id"])
            bad = copy.deepcopy(row.payload)
            bad["name"] = "relabelled"
            row.payload = bad
            session.commit()
        assert client.post("/api/simulations/compare", json=body).status_code == 409
