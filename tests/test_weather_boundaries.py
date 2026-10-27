import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from packages.domain.models import MissionConfig, digest
from packages.meteo.field import GridField, WeatherDomainError, geometric_m
from services.api import worker
from services.api.main import create_app
from services.api.storage import Job, Record


def surface_grid():
    start = datetime(2026, 10, 27, tzinfo=UTC).timestamp()
    shape = (2, 3, 2, 2)
    h = np.broadcast_to(np.array([0, 5000, 12000])[None, :, None, None], shape)
    surface_shape = (2, 2, 2)
    return GridField(
        [start, start + 3600],
        [40, 41],
        [0, 1],
        [100000, 50000, 20000],
        np.full(shape, 10),
        np.zeros(shape),
        np.full(shape, 250),
        h,
        {"provider": "NOAA_GFS"},
        surface={
            "height": np.full(surface_shape, 100),
            "pressure": np.full(surface_shape, 99000),
            "u": np.full(surface_shape, 2),
            "v": np.zeros(surface_shape),
            "temperature": np.full(surface_shape, 288),
        },
    )


def test_surface_wind_boundary_and_below_terrain_rejection():
    grid = surface_grid()
    time = datetime(2026, 10, 27, tzinfo=UTC)
    assert grid.get_state(40.5, 0.5, geometric_m(100), time).u_ms == 2
    with pytest.raises(WeatherDomainError, match="terrain"):
        grid.get_state(40.5, 0.5, 50, time)


def test_future_initialized_weather_is_rejected_by_worker(tmp_path, monkeypatch):
    class FutureField:
        provenance = {"provider": "NOAA_GFS", "run_utc": "2026-10-27T18:00:00+00:00"}

    monkeypatch.setattr(worker, "open_cached", lambda _, **kw: FutureField())
    app = create_app(tmp_path, seed=False)
    config = MissionConfig().model_dump(mode="json")
    config["schema_version"] = 1
    config["weather"] = {"provider": "NOAA_GFS", "dataset_id": "test-future"}
    with TestClient(app) as client:
        rev = client.post("/api/missions", json=config).json()
        with app.state.sessions() as session:
            session.add(
                Record(
                    id="test-future",
                    kind="dataset",
                    payload={
                        "run_utc": "2026-10-27T18:00:00+00:00",
                        "valid_start_utc": "2026-10-27T18:00:00+00:00",
                        "valid_end_utc": "2026-10-27T20:00:00+00:00",
                    },
                )
            )
            session.commit()
        rejected = client.post("/api/simulations", json={"revision_id": rev["id"]})
        assert rejected.status_code == 422
        assert "look-ahead rejected" in rejected.json()["detail"]
        job = {"id": str(uuid4())}
        with app.state.sessions() as session:
            session.add(Job(id=job["id"], kind="simulation", payload={"revision_id": rev["id"]}))
            session.commit()
        worker.run_one(app.state.sessions, tmp_path)
        result = client.get(f"/api/jobs/{job['id']}").json()
        assert result["status"] == "failed"
        assert "look-ahead rejected" in result["message"]
        assert client.get("/api/simulations").json() == []


def test_saved_results_survive_new_application_instance(tmp_path):
    config = MissionConfig().model_dump(mode="json")
    config["id"] = str(uuid4())
    config["flight"].update(initial_geometric_m=12500, float_duration_hours=0.01)
    app = create_app(tmp_path, seed=False)
    with TestClient(app) as client:
        rev = client.post("/api/missions", json=config).json()
        job = client.post("/api/simulations", json={"revision_id": rev["id"]}).json()
        worker.run_one(app.state.sessions, tmp_path)
        result_id = client.get(f"/api/jobs/{job['id']}").json()["result_id"]
        saved = client.get(f"/api/simulations/{result_id}").json()
    # New engine, application lifespan and migration run: read committed state again.
    with TestClient(create_app(tmp_path, seed=False)) as fresh:
        restored = fresh.get(f"/api/simulations/{result_id}").json()
        assert restored == saved
        assert restored["manifest"]["sha256"] == digest(
            {k: v for k, v in restored["manifest"].items() if k != "sha256"}
        )
        assert restored["manifest"]["weather"]["provider"] == "SYNTHETIC"
        assert fresh.get(f"/api/jobs/{job['id']}").json()["updated_utc"].endswith("+00:00")
    assert json.loads((tmp_path / "simulations" / f"{result_id}.json").read_text()) == saved


def test_forecast_horizon_error_stops_integration():
    from packages.flight.integrator import simulate

    config = MissionConfig()
    config.launch.latitude_deg, config.launch.longitude_deg = 40.5, 0.5
    config.launch.start_utc = datetime(2026, 10, 27, tzinfo=UTC) + timedelta(minutes=59)
    config.flight.initial_geometric_m = config.flight.target_geometric_m = 1000
    config.flight.float_duration_hours = 0.1
    with pytest.raises(WeatherDomainError, match="horizon"):
        simulate(config, surface_grid())
