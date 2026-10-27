import copy
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.domain.integrity import verify_simulation
from packages.domain.models import MissionConfig
from packages.meteo.gfs import sha256_file
from scripts.backup import backup
from services.api.main import create_app
from services.api.storage import Job, Record
from services.api.worker import run_one


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other-run"),
        ("name", "mislabelled study"),
        ("weather_provider", "SYNTHETIC"),
        ("created_utc", "2000-01-01T00:00:00Z"),
        ("manifest", {}),
    ],
)
def test_saved_identifiers_and_labels_are_verified_not_just_output_hash(field, value):
    original = json.loads((Path(__file__).parents[1] / "docs/examples/noaa-simulation.json").read_text())
    verify_simulation(original, original["id"])
    bad = copy.deepcopy(original)
    bad[field] = value
    with pytest.raises(ValueError, match="integrity check failed"):
        verify_simulation(bad, original["id"])


def test_backup_recovers_missing_duplicate_from_verified_database_and_rejects_bad_label(tmp_path):
    live = tmp_path / "live"
    app = create_app(live, seed=False)
    with TestClient(app) as client:
        config = MissionConfig().model_dump(mode="json")
        config["flight"].update(initial_geometric_m=12500, float_duration_hours=0.01)
        revision = client.post("/api/missions", json=config).json()
        job = client.post("/api/simulations", json={"revision_id": revision["id"]}).json()
        run_one(app.state.sessions, live)
        ident = client.get("/api/jobs/" + job["id"]).json()["result_id"]
        expected = client.get("/api/simulations/" + ident).json()
        (live / "simulations" / (ident + ".json")).unlink()
        manifest = backup(live, tmp_path / "good")
        assert manifest["reconstructed_simulation_files"] == [ident + ".json"]
        assert manifest["validated_simulation_ids"] == [ident]
        restored = tmp_path / "good/simulations" / (ident + ".json")
        assert json.loads(restored.read_text()) == expected
        assert sha256_file(restored) == manifest["files"]["simulations/" + ident + ".json"]
        with app.state.sessions() as session:
            row = session.get(Record, ident)
            row.payload = {**row.payload, "name": "different mission"}
            session.commit()
        assert client.get("/api/simulations/" + ident).status_code == 409
        assert client.get("/api/simulations/" + ident + "/export").status_code == 409
        with pytest.raises(ValueError, match="integrity check failed"):
            backup(live, tmp_path / "bad")
        assert (tmp_path / "bad/BACKUP_FAILED").is_file()


@pytest.mark.parametrize("status", ["queued", "running"])
def test_backup_refuses_active_snapshot_without_modifying_live_job(tmp_path, status):
    app = create_app(tmp_path / "live", seed=False)
    with TestClient(app):
        with app.state.sessions() as session:
            session.add(Job(id="active", kind="weather", status=status, payload={}))
            session.commit()
        with pytest.raises(ValueError, match="idle job queue"):
            backup(tmp_path / "live", tmp_path / "backup")
        assert (tmp_path / "backup/BACKUP_FAILED").is_file()
        with app.state.sessions() as session:
            assert session.get(Job, "active").status == status


def test_backup_checks_required_real_raw_inputs_against_forecast_not_its_own_copy(tmp_path):
    live = tmp_path / "live"
    source = Path(__file__).parent / "fixtures/noaa-gfs-20261027-06"
    metadata = json.loads((source / "manifest.json").read_text())
    cache = live / "cache" / metadata["id"]
    shutil.copytree(source, cache)
    app = create_app(live, seed=False)
    with TestClient(app):
        with app.state.sessions() as session:
            session.add(Record(id=metadata["id"], kind="dataset", payload=metadata))
            session.commit()
        good = backup(live, tmp_path / "good")
        assert good["validated_weather_ids"] == [metadata["id"]]
        raw = cache / "f006.grib2"
        original = raw.read_bytes()
        raw.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with pytest.raises(ValueError, match="raw checksum mismatch"):
            backup(live, tmp_path / "bad")
        assert (tmp_path / "bad/BACKUP_FAILED").is_file()


def test_verify_and_restore_frozen_backup_without_writes_or_overwrite(tmp_path):
    from scripts.verify_backup import restore_backup, verify_backup

    app = create_app(tmp_path / "live", seed=False)
    with TestClient(app):
        backup(tmp_path / "live", tmp_path / "backup")
    frozen = tmp_path / "backup"
    before = {p.relative_to(frozen).as_posix(): sha256_file(p) for p in frozen.rglob("*") if p.is_file()}
    assert verify_backup(frozen)["status"] == "verified"
    after = {p.relative_to(frozen).as_posix(): sha256_file(p) for p in frozen.rglob("*") if p.is_file()}
    assert before == after
    assert not list(frozen.glob("*-wal")) and not list(frozen.glob("*-shm"))
    assert restore_backup(frozen, tmp_path / "restored")["status"] == "verified"
    with pytest.raises(FileExistsError):
        restore_backup(frozen, tmp_path / "restored")
    with pytest.raises(ValueError, match="outside"):
        restore_backup(frozen, frozen / "nested")
    restored = tmp_path / "restored"
    (restored / "unexpected").write_text("unverified")
    with pytest.raises(ValueError, match="inventory differs"):
        verify_backup(restored)
    (restored / "unexpected").unlink()
    database = restored / "stratos.sqlite3"
    database.write_bytes(database.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_backup(restored)
    with pytest.raises(ValueError):
        restore_backup(restored, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
