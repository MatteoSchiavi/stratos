from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from packages.domain.models import Cancelled, DownloadRequest, ExpansionPolicy, MissionConfig
from packages.flight.geojson import geometry
from packages.meteo.adaptive import AdaptiveField
from packages.meteo.explorer import explore
from packages.meteo.field import GridField, WeatherDomainError
from packages.meteo.gfs import sha256_file
from scripts.backup import backup
from services.api.main import create_app
from services.api.storage import Record
from services.api.worker import run_one

RUN = datetime(2026, 10, 27, 6, tzinfo=UTC)


def field(request=None, ident="base", bias=0):
    request = request or DownloadRequest(
        run_utc=RUN, first_lead_hour=0, last_lead_hour=2, west_deg=0, east_deg=6, south_deg=0, north_deg=6
    )
    lats = np.array([request.south_deg, request.north_deg])
    lons = np.array([request.west_deg, request.east_deg])
    times = [
        (RUN + timedelta(hours=i)).timestamp()
        for i in range(request.first_lead_hour, request.last_lead_hour + 1)
    ]
    shape = (len(times), 3, 2, 2)
    h = np.broadcast_to(np.array([0, 5000, 12000])[None, :, None, None], shape)
    u = np.broadcast_to(lons[None, None, None, :], shape) + bias
    metadata = {
        "id": ident,
        "provider": "NOAA_GFS",
        "run_utc": RUN.isoformat(),
        "member": "deterministic",
        "grid_deg": 0.25,
        "request": request.model_dump(mode="json"),
        "files": [{"size_bytes": 100}],
    }
    return GridField(
        times, lats, lons, [100000, 50000, 20000], u, np.zeros(shape), np.full(shape, 250), h, metadata
    )


def adaptive(*, bias=0, limit=4, cancel=False):
    registry = {"base": field()}
    requests = []

    def fetch(request, *_, **kw):
        requests.append(request)
        registry["adjacent"] = field(request, "adjacent", bias)
        return registry["adjacent"].provenance

    wrapper = AdaptiveField(
        registry["base"],
        Path("/tmp"),
        ExpansionPolicy(max_tiles=limit),
        cancelled=lambda: cancel,
        fetcher=fetch,
        loader=lambda p, **kw: registry[p.name],
    )
    return wrapper, requests


def test_pinned_adjacent_weather_crossing_and_reuse():
    weather, requests = adaptive()
    assert weather.get_state(1, 5.9, 1000, RUN).u_ms == pytest.approx(5.9)
    assert weather.get_state(1, 6.1, 1000, RUN).u_ms == pytest.approx(6.1)
    assert weather.get_state(1, 6.2, 1000, RUN).u_ms == pytest.approx(6.2)
    assert len(requests) == 1
    assert requests[0].run_utc == RUN
    assert weather.provenance["segment_count"] == 2
    assert weather.provenance["overlap_checks"][0]["status"] == "matched"


def test_inconsistent_overlap_quotas_and_cancellation_are_blocking():
    weather, _ = adaptive(bias=2)
    with pytest.raises(WeatherDomainError, match="overlap disagrees"):
        weather.get_state(1, 6.1, 1000, RUN)
    weather, requests = adaptive(limit=1)
    with pytest.raises(WeatherDomainError, match="quota"):
        weather.get_state(1, 6.1, 1000, RUN)
    assert requests == []
    weather, _ = adaptive(cancel=True)
    with pytest.raises(Cancelled):
        weather.get_state(1, 6.1, 1000, RUN)
    weather, requests = adaptive()
    with pytest.raises(WeatherDomainError, match="horizon"):
        weather.get_state(1, 6.1, 1000, RUN + timedelta(hours=3))
    assert requests == []


def test_weather_input_budget_counts_retained_sources():
    f = field()
    f.provenance["files"] = [{"size_bytes": 2 * 1048576}]
    with pytest.raises(WeatherDomainError, match="input-byte budget"):
        AdaptiveField(f, Path("/tmp"), ExpansionPolicy(max_download_mib=1))


def test_geojson_splits_dateline_and_does_not_mislabel_msl_as_ellipsoid():
    result = geometry(
        [{"latitude_deg": 40, "longitude_deg": 179}, {"latitude_deg": 42, "longitude_deg": -179}]
    )
    assert result["type"] == "MultiLineString"
    assert result["coordinates"] == [[[179, 40], [180, 41]], [[-180, 41], [-179, 42]]]
    assert all(len(point) == 2 for segment in result["coordinates"] for point in segment)


def test_consistent_backup_and_corrupted_output_rejected(tmp_path):
    data = tmp_path / "live"
    app = create_app(data, seed=False)
    with TestClient(app) as client:
        config = MissionConfig().model_dump(mode="json")
        config["flight"].update(initial_geometric_m=12500, float_duration_hours=0.01)
        revision = client.post("/api/missions", json=config).json()
        job = client.post("/api/simulations", json={"revision_id": revision["id"]}).json()
        run_one(app.state.sessions, data)
        ident = client.get("/api/jobs/" + job["id"]).json()["result_id"]
        expected = client.get("/api/simulations/" + ident).json()
        manifest = backup(data, tmp_path / "backup")
        assert "stratos.sqlite3" in manifest["files"]
        assert not any(name.endswith(("-wal", "-shm")) for name in manifest["files"])
        for name, checksum in manifest["files"].items():
            assert sha256_file(tmp_path / "backup" / name) == checksum
        with app.state.sessions() as session:
            row = session.get(Record, ident)
            bad = dict(row.payload)
            bad["distance_m"] += 10
            row.payload = bad
            session.commit()
        assert client.get("/api/simulations/" + ident + "/export").status_code == 409
    with TestClient(create_app(tmp_path / "backup", seed=False)) as recovered:
        assert recovered.get("/api/simulations/" + ident).json() == expected
    with pytest.raises(FileExistsError):
        backup(data, tmp_path / "backup")
    with pytest.raises(ValueError):
        backup(data, data / "nested")


def test_synthetic_weather_inspection_reports_actual_column_and_vectors():
    from packages.domain.models import ExploreRequest

    result = explore(
        field(),
        ExploreRequest(
            dataset_id="base", time_utc=RUN, latitude_deg=1, longitude_deg=1, geometric_msl_m=1000
        ),
    )
    assert result["point"]["u_ms"] == pytest.approx(1)
    assert len(result["profile"]) == 3
    assert len(result["wind_vectors"]["features"]) == 81
    assert result["unavailable_cells"] == 0
    assert result["vector_scale_seconds"] == 600


def test_real_cached_weather_explorer_api_without_network(tmp_path):
    import shutil

    source = Path(__file__).parent / "fixtures/noaa-gfs-20261027-06"
    metadata = __import__("json").loads((source / "manifest.json").read_text())
    target = tmp_path / "cache" / metadata["id"]
    shutil.copytree(source, target)
    app = create_app(tmp_path, seed=False)
    with TestClient(app) as client:
        with app.state.sessions() as session:
            session.add(Record(id=metadata["id"], kind="dataset", payload=metadata))
            session.commit()
        response = client.post(
            "/api/weather/explore",
            json={
                "dataset_id": metadata["id"],
                "time_utc": "2026-10-27T12:30:00Z",
                "latitude_deg": 45,
                "longitude_deg": 9.75,
                "geometric_msl_m": 12500,
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["quality"] == "forecast_not_observation"
        assert len(result["profile"]) > 15
        assert len(result["wind_vectors"]["features"]) == 81
        assert result["provenance"]["sha256"] == metadata["sha256"]
        bad = client.post(
            "/api/weather/explore",
            json={
                "dataset_id": metadata["id"],
                "time_utc": "2026-10-27T14:00:00Z",
                "latitude_deg": 45,
                "longitude_deg": 9.75,
                "geometric_msl_m": 12500,
            },
        )
        assert bad.status_code == 422


def test_worker_health_and_archive_pagination(tmp_path):
    from packages.domain.models import utcnow

    app = create_app(tmp_path, seed=False)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["worker"]["state"] == "unavailable"
        with app.state.sessions() as session:
            session.add(
                Record(id="runtime_worker", kind="runtime", payload={"heartbeat_utc": utcnow().isoformat()})
            )
            for i in range(5):
                session.add(
                    Record(
                        id=f"archive-{i}",
                        kind="simulation",
                        payload={
                            "name": f"run {i}",
                            "samples": [{"large": "data"}] * 100,
                            "distance_m": i,
                            "duration_s": 10,
                        },
                    )
                )
            session.commit()
        assert client.get("/api/health").json()["worker"]["state"] == "ready"
        first = client.get("/api/simulations?limit=2&offset=0").json()
        second = client.get("/api/simulations?limit=2&offset=2").json()
        assert len(first) == len(second) == 2
        assert not set(r["id"] for r in first) & set(r["id"] for r in second)
        assert all("samples" not in r for r in first)
        assert client.get("/api/summary").json()["simulations"] == 5
        assert client.get("/api/simulations?limit=101").status_code == 422


def test_retry_preserves_original_payload_and_completed_jobs_are_not_retried(tmp_path):
    app = create_app(tmp_path, seed=False)
    with TestClient(app) as client:
        config = MissionConfig().model_dump(mode="json")
        config["flight"].update(initial_geometric_m=12500, float_duration_hours=0.01)
        revision = client.post("/api/missions", json=config).json()
        job = client.post("/api/simulations", json={"revision_id": revision["id"]}).json()
        client.post("/api/jobs/" + job["id"] + "/cancel")
        retried = client.post("/api/jobs/" + job["id"] + "/retry")
        assert retried.status_code == 202
        assert retried.json()["id"] != job["id"]
        run_one(app.state.sessions, tmp_path)
        done = client.get("/api/jobs/" + retried.json()["id"]).json()
        assert done["status"] == "completed"
        result = client.get("/api/simulations/" + done["result_id"]).json()
        assert result["revision_id"] == revision["id"]
        assert client.post("/api/jobs/" + retried.json()["id"] + "/retry").status_code == 409


def test_source_identity_guard_accepts_ui_edits_but_rejects_scientific_changes():
    from services.api.provenance import assert_runtime_unchanged

    loaded = {
        "scientific_source_sha256": "python-1",
        "source_tree_sha256": "ui-1",
        "packages": {"numpy": "2.5.4"},
    }
    assert_runtime_unchanged(loaded, {**loaded, "source_tree_sha256": "ui-2"})
    with pytest.raises(ValueError, match="restart the API/worker"):
        assert_runtime_unchanged(loaded, {**loaded, "scientific_source_sha256": "python-2"})
    with pytest.raises(ValueError, match="dependencies changed"):
        assert_runtime_unchanged(loaded, {**loaded, "packages": {"numpy": "other"}})


def test_overlap_source_precedence_does_not_depend_on_lru_order():
    weather, _ = adaptive(bias=0.005)
    weather.get_state(1, 6.1, 1000, RUN)
    # Both crops agree within declared packing tolerance, but the original source
    # must always win in its own overlap, even if the adjacent crop was just used.
    assert weather.get_state(1, 5.9, 1000, RUN).u_ms == pytest.approx(5.9)
    weather.get_state(1, 6.2, 1000, RUN)
    assert weather.get_state(1, 5.9, 1000, RUN).u_ms == pytest.approx(5.9)


def test_stale_worker_cannot_publish_a_new_prediction(tmp_path, monkeypatch):
    from services.api import provenance, worker

    app = create_app(tmp_path, seed=False)
    with TestClient(app) as client:
        config = MissionConfig().model_dump(mode="json")
        config["flight"].update(initial_geometric_m=12500, float_duration_hours=0.01)
        revision = client.post("/api/missions", json=config).json()
        job = client.post("/api/simulations", json={"revision_id": revision["id"]}).json()
        stale = {**worker.RUNTIME_CODE, "scientific_source_sha256": "different-loaded-code"}
        monkeypatch.setattr(provenance, "code_identity", lambda: stale)
        worker.run_one(app.state.sessions, tmp_path)
        failed = client.get("/api/jobs/" + job["id"]).json()
        assert failed["status"] == "failed"
        assert "changed after worker startup" in failed["message"]
        assert client.get("/api/simulations").json() == []
        assert not list((tmp_path / "simulations").glob("*.json"))


def test_backup_cannot_certify_a_missing_or_unrelated_database(tmp_path):
    import sqlite3

    source = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        backup(source, tmp_path / "backup")
    assert not (source / "stratos.sqlite3").exists()
    assert not (tmp_path / "backup").exists()
    source.mkdir()
    with sqlite3.connect(source / "stratos.sqlite3") as db:
        db.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(ValueError, match="not an initialized STRATOS database"):
        backup(source, tmp_path / "invalid-backup")
    assert (tmp_path / "invalid-backup/BACKUP_FAILED").exists()
