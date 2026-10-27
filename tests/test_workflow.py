import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from packages.domain.models import DownloadRequest, MissionConfig, digest
from services.api.main import create_app
from services.api.storage import Job
from services.api.worker import recover_interrupted, run_one


@pytest.fixture
def local_app(tmp_path):
    app = create_app(tmp_path, seed=False)
    with TestClient(app) as client:
        yield client, app.state.sessions, tmp_path


def short_config():
    config = MissionConfig().model_dump(mode="json")
    config["flight"].update(initial_geometric_m=12500, float_duration_hours=0.05)
    return config


def test_complete_save_run_reopen_hashes_and_exports(local_app):
    client, factory, data = local_app
    config = short_config()
    response = client.post("/api/missions", json=config)
    assert response.status_code == 201
    revision = response.json()
    job = client.post("/api/simulations", json={"revision_id": revision["id"]}).json()
    assert job["status"] == "queued"
    assert run_one(factory, data)
    completed = client.get(f"/api/jobs/{job['id']}").json()
    assert completed["status"] == "completed", completed
    result_id = completed["result_id"]
    result = client.get(f"/api/simulations/{result_id}").json()
    manifest = dict(result["manifest"])
    checksum = manifest.pop("sha256")
    assert checksum == digest(manifest)
    metadata = {"id", "name", "created_utc", "revision_id", "operating_mode", "weather_provider", "manifest"}
    output = {k: v for k, v in result.items() if k not in metadata}
    assert digest(output) == manifest["output_sha256"]
    assert manifest["config_sha256"] == MissionConfig.model_validate(config).revision_hash
    exported = client.get(f"/api/simulations/{result_id}/export").json()
    assert exported == result == client.get(f"/api/simulations/{result_id}").json()
    assert json.loads((data / "simulations" / f"{result_id}.json").read_text()) == result
    assert len(client.get(f"/api/simulations/{result_id}/export?format=csv").text.splitlines()) > 2
    assert client.get(f"/api/simulations/{result_id}/trajectory").json()["geometry"]["type"] == "LineString"
    # A second independently computed run must have the same physical output hash.
    repeat = client.post("/api/simulations", json={"revision_id": revision["id"]}).json()
    run_one(factory, data)
    repeated_id = client.get(f"/api/jobs/{repeat['id']}").json()["result_id"]
    assert (
        client.get(f"/api/simulations/{repeated_id}").json()["manifest"]["output_sha256"]
        == manifest["output_sha256"]
    )


def test_mission_yaml_roundtrip_and_immutable_revisions(local_app):
    client, _, _ = local_app
    config = short_config()
    first = client.post("/api/missions", json=config).json()
    doc = client.get(f"/api/revisions/{first['id']}/yaml").text
    assert yaml.safe_load(doc) == config
    config["flight"]["payload_mass_g"] = 40
    second = client.post(f"/api/missions/{config['id']}/revisions", json=config).json()
    assert first["config_sha256"] != second["config_sha256"]
    assert client.get(f"/api/revisions/{first['id']}").json()["config"]["flight"]["payload_mass_g"] == 23
    imported = client.post(
        "/api/missions/import-yaml", content=doc, headers={"Content-Type": "application/yaml"}
    )
    assert imported.status_code == 201
    assert imported.json()["config_sha256"] == first["config_sha256"]


def test_cancellation_and_interruption(local_app):
    client, factory, data = local_app
    revision = client.post("/api/missions", json=short_config()).json()
    job = client.post("/api/simulations", json={"revision_id": revision["id"]}).json()
    assert client.post(f"/api/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    assert not run_one(factory, data)
    with factory() as session:
        session.add(Job(id=str(uuid4()), kind="simulation", status="running", payload={}))
        session.commit()
    recover_interrupted(factory)
    assert "interrupted" in [j["status"] for j in client.get("/api/jobs").json()]


def test_invalid_and_unsupported_configs_are_visible(local_app):
    client, _, _ = local_app
    config = short_config()
    config["flight"]["ascent_ms"] = -1
    assert client.post("/api/missions", json=config).status_code == 422
    config = short_config()
    config["operating_mode"] = "LIVE"
    revision = client.post("/api/missions", json=config).json()
    assert client.post("/api/simulations", json={"revision_id": revision["id"]}).status_code == 422
    config = short_config()
    config["launch"]["start_utc"] = "2026-10-27T12:00:00"
    assert client.post("/api/missions", json=config).status_code == 422


def test_write_security_and_import_limits(local_app):
    client, _, _ = local_app
    assert (
        client.post(
            "/api/missions", json=short_config(), headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.post("/api/missions/import-yaml", content="a" * 70000).status_code == 413
    assert client.post("/api/missions/import-yaml", content="!!python/object:os.system {}").status_code == 422


def test_download_bounds():
    with pytest.raises(ValueError, match="cycle"):
        DownloadRequest(run_utc=datetime(2026, 10, 27, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="without crossing"):
        DownloadRequest(run_utc=datetime(2026, 10, 27, 0, tzinfo=UTC), west_deg=170, east_deg=-170)
