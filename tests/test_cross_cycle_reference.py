"""Actual retained NOAA files, same valid time, two forecast cycles; entirely offline."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from geographiclib.geodesic import Geodesic

from packages.meteo.gfs import read_manifest, sha256_file
from services.api.main import create_app
from services.api.worker import run_one


def test_controlled_forecast_cycle_workflow_uses_original_noaa_bytes(tmp_path):
    root = Path(__file__).parent / "fixtures"
    manifests = []
    for hour in ("06", "12"):
        folder = root / ("noaa-cross-cycle-20261027-" + hour)
        manifest = read_manifest(folder)
        origin = json.loads((folder / "subset-provenance.json").read_text())
        assert origin["kind"] == "retained_exact_hourly_subset"
        for record in manifest["files"]:
            assert sha256_file(folder / record["file"]) == record["sha256"]
            assert record["sha256"] == origin["selected_file_sha256"][record["file"]]
        assert manifest["valid_start_utc"] == "2026-10-27T18:00:00+00:00"
        assert manifest["valid_end_utc"] == "2026-10-27T19:00:00+00:00"
        manifests.append(manifest)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert len(client.get("/api/weather/datasets").json()) == 3
        run_one(app.state.sessions, tmp_path)  # Initial actual synthetic reference calculation.
        mission = client.get("/api/missions").json()[0]
        config = client.get("/api/revisions/" + mission["latest_revision_id"]).json()["config"]
        config["launch"]["start_utc"] = "2026-10-27T18:00:00Z"
        config["flight"].update(initial_geometric_m=12500, target_geometric_m=12500, float_duration_hours=1)
        results = []
        for metadata in manifests:
            config["weather"] = {"provider": "NOAA_GFS", "dataset_id": metadata["id"]}
            revision = client.post("/api/missions/" + config["id"] + "/revisions", json=config).json()
            submitted = client.post("/api/simulations", json={"revision_id": revision["id"]})
            assert submitted.status_code == 202, submitted.text
            run_one(app.state.sessions, tmp_path)
            job = client.get("/api/jobs/" + submitted.json()["id"]).json()
            assert job["status"] == "completed", job
            result = client.get("/api/simulations/" + job["result_id"]).json()
            assert len(result["samples"]) == 31
            assert result["weather_provider"] == "NOAA_GFS"
            assert all(row["quality"] == "modeled_uncalibrated" for row in result["samples"])
            results.append(result)
        compared = client.post(
            "/api/simulations/compare",
            json={
                "reference_id": results[0]["id"],
                "candidate_id": results[1]["id"],
                "alignment": "utc",
                "sample_count": 121,
            },
        )
        assert compared.status_code == 200, compared.text
        value = compared.json()
        end_a, end_b = results[0]["samples"][-1], results[1]["samples"][-1]
        expected = Geodesic.WGS84.Inverse(
            end_a["latitude_deg"], end_a["longitude_deg"], end_b["latitude_deg"], end_b["longitude_deg"]
        )["s12"]
        assert abs(value["metrics"]["shared_window_end_separation_m"] - expected) < 1e-7
        assert expected > 0.01
        assert [row["field"] for row in value["configuration_differences"]] == ["weather.dataset_id"]
        assert value["sources"][0]["weather_run_utc"] != value["sources"][1]["weather_run_utc"]
