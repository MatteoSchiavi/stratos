"""Consistent SQLite snapshot plus verified inputs/outputs; never overwrites a backup."""

import argparse
import json
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from packages.domain.integrity import verify_simulation
from packages.domain.models import utcnow
from packages.meteo.gfs import atomic_json, read_manifest, sha256_file
from services.api.storage import DATA


def snapshot_records(connection: sqlite3.Connection) -> tuple[dict[str, dict], dict[str, str]]:
    simulations: dict[str, dict] = {}
    forecasts: dict[str, str] = {}

    def require_forecast(metadata):
        if metadata.get("provider") != "NOAA_GFS":
            return
        ident, checksum = metadata["id"], metadata["sha256"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", ident):
            raise ValueError("Unsafe forecast cache identifier in saved evidence")
        if ident in forecasts and forecasts[ident] != checksum:
            raise ValueError("Conflicting forecast identities in saved evidence")
        forecasts[ident] = checksum

    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("Backup database failed SQLite integrity check")
    active = connection.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[
        0
    ]
    if active:
        raise ValueError("Backup requires an idle job queue; finish or cancel queued/running jobs and retry")
    for ident, kind, raw in connection.execute(
        "SELECT id,kind,payload FROM records WHERE kind IN ('dataset','simulation')"
    ):
        payload = json.loads(raw)
        if kind == "dataset":
            if payload.get("provider") != "NOAA_GFS":
                raise ValueError("Unsupported provider in finalized forecast registry")
            if payload.get("id") != ident:
                raise ValueError("Dataset registry identifier differs from saved forecast")
            require_forecast(payload)
        else:
            verify_simulation(payload, ident)
            simulations[ident] = payload
            weather = payload["manifest"]["weather"]
            require_forecast(weather)
            for segment in weather.get("segments", []):
                require_forecast(segment)
    return simulations, forecasts


def verify_weather_inputs(root: Path, forecasts: dict[str, str]) -> None:
    for ident, checksum in forecasts.items():
        folder = root / "cache" / ident
        metadata = read_manifest(folder)
        if metadata["id"] != ident or metadata["sha256"] != checksum:
            raise ValueError("Required forecast manifest identity differs from database snapshot: " + ident)
        for record in metadata["files"]:
            if sha256_file(folder / record["file"]) != record["sha256"]:
                raise ValueError("Required forecast raw checksum mismatch: " + ident + "/" + record["file"])


def backup(data: Path, destination: Path) -> dict:
    data, destination = data.resolve(), destination.resolve()
    if destination == data or data in destination.parents:
        raise ValueError("Backup must be outside the live data directory")
    if not (data / "stratos.sqlite3").is_file():
        raise FileNotFoundError(
            "No initialized STRATOS database at the selected data directory; no backup created"
        )
    destination.mkdir(parents=True, exist_ok=False)
    try:
        # Connection's own context manager commits but does not close. Explicit
        # closure checkpoints the target before hashing; transient WAL/SHM files
        # must not enter a manifest and disappear after this function returns.
        with (
            closing(sqlite3.connect((data / "stratos.sqlite3").as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(destination / "stratos.sqlite3")) as target,
        ):
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"records", "jobs", "alembic_version"} <= tables:
                raise ValueError("Source database is not an initialized STRATOS database")
            source.backup(target)
            simulations, forecasts = snapshot_records(target)
        for directory in ("cache", "simulations"):
            if (data / directory).exists():
                if (
                    any(p.is_symlink() for p in (data / directory).rglob("*"))
                    or (data / directory).is_symlink()
                ):
                    raise ValueError("Backup input directories must not contain symlinks")
                shutil.copytree(
                    data / directory,
                    destination / directory,
                    ignore=shutil.ignore_patterns("*.part", "*.tmp", "*.lock"),
                )
        verify_weather_inputs(destination, forecasts)
        reconstructed = []
        for ident, payload in simulations.items():
            path = destination / "simulations" / (ident + ".json")
            try:
                matches = json.loads(path.read_text()) == payload
            except (OSError, ValueError):
                matches = False
            if not matches:
                # SQLite is authoritative; salvage a missing/damaged redundant
                # export only after its complete saved evidence has been verified.
                atomic_json(path, payload)
                reconstructed.append(ident + ".json")
        manifest = {
            "schema_version": 2,
            "created_utc": utcnow().isoformat(),
            "source": "STRATOS local SQLite backup API",
            "snapshot_scope": "Finalized database snapshot; jobs added after snapshot are excluded. Copied unreferenced files are supplementary.",
            "validated_simulation_ids": sorted(simulations),
            "validated_weather_ids": sorted(forecasts),
            "reconstructed_simulation_files": sorted(reconstructed),
            "files": {
                p.relative_to(destination).as_posix(): sha256_file(p)
                for p in destination.rglob("*")
                if p.is_file()
            },
        }
        atomic_json(destination / "backup-manifest.json", manifest)
        return manifest
    except Exception:
        (destination / "BACKUP_FAILED").write_text(
            "Backup did not complete; do not restore as a complete snapshot.\n"
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = backup(DATA, args.output)
    print(f"Verified local backup: {len(manifest['files'])} files at {args.output}")
