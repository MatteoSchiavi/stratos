"""Make a retained, explicitly dated NOAA reference available entirely offline."""

import logging
import shutil
from pathlib import Path

from packages.meteo.gfs import read_manifest, sha256_file
from services.api.storage import ROOT, Record


def register_reference(session_factory, data: Path):
    for name in (
        "noaa-gfs-20261027-06-regional",
        "noaa-cross-cycle-20261027-06",
        "noaa-cross-cycle-20261027-12",
    ):
        _register(session_factory, data, ROOT / "tests/fixtures" / name)


def _register(session_factory, data: Path, source: Path):
    if not source.exists():
        return
    manifest = read_manifest(source)
    with session_factory() as session:
        if session.get(Record, manifest["id"]):
            return
        destination = data / "cache" / manifest["id"]
        destination.mkdir(parents=True, exist_ok=True)
        for record in manifest["files"]:
            target = destination / record["file"]
            if sha256_file(source / record["file"]) != record["sha256"]:
                raise ValueError("Bundled NOAA reference checksum failed")
            if target.exists() and sha256_file(target) != record["sha256"]:
                logging.getLogger(__name__).warning(
                    "Existing local NOAA file differs; preserving it instead of importing the reference"
                )
                return
        for path in source.iterdir():
            target = destination / path.name
            if path.is_file() and not target.exists():
                shutil.copy2(path, target)
        if read_manifest(destination)["sha256"] != manifest["sha256"]:
            raise ValueError("Existing weather manifest differs from bundled reference; not registered")
        session.add(Record(id=manifest["id"], kind="dataset", payload=manifest))
        session.commit()
