"""Read-only archive verification and optional restore into a new directory."""

import argparse
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from packages.meteo.gfs import sha256_file
from scripts.backup import snapshot_records, verify_weather_inputs


def verify_backup(root: Path) -> dict:
    root = root.resolve()
    if (root / "BACKUP_FAILED").exists() or (root / "RESTORE_FAILED").exists():
        raise ValueError("Snapshot is explicitly marked failed; it is not a verified backup")
    manifest = json.loads((root / "backup-manifest.json").read_text())
    expected = manifest["files"]
    if not isinstance(expected, dict) or "stratos.sqlite3" not in expected:
        raise ValueError("Backup manifest lacks a database file inventory")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Backup must not contain symlinks")
        if path.is_file() and path != root / "backup-manifest.json":
            actual.add(path.relative_to(root).as_posix())
    if actual != set(expected):
        raise ValueError("Backup inventory differs: missing or unexpected files")
    for name, checksum in expected.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("Unsafe relative path in backup inventory")
        if name.endswith(("-wal", "-shm")):
            raise ValueError(
                "Backup retains a transient SQLite journal; a closed/checkpointed snapshot is required"
            )
        if sha256_file(root / relative) != checksum:
            raise ValueError("Backup file checksum mismatch: " + name)
    # This is a closed frozen snapshot; immutable read mode neither writes nor
    # creates SHM/WAL files, and cannot silently merge an unlisted journal.
    with closing(
        sqlite3.connect((root / "stratos.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
    ) as db:
        simulations, forecasts = snapshot_records(db)
    verify_weather_inputs(root, forecasts)
    for ident, expected_result in simulations.items():
        if json.loads((root / "simulations" / (ident + ".json")).read_text()) != expected_result:
            raise ValueError("Redundant simulation export differs from verified database: " + ident)
    return {
        "files": len(expected),
        "simulations": len(simulations),
        "weather_sources": len(forecasts),
        "status": "verified",
    }


def restore_backup(root: Path, destination: Path) -> dict:
    root, destination = root.resolve(), destination.resolve()
    verify_backup(root)
    if destination.exists():
        raise FileExistsError("Restore destination already exists; select a new directory")
    if destination == root or root in destination.parents:
        raise ValueError("Restore destination must be outside the backup")
    try:
        shutil.copytree(root, destination)
        return verify_backup(destination)
    except Exception:
        if destination.is_dir():
            (destination / "RESTORE_FAILED").write_text(
                "Restore did not complete; do not start services against this directory.\n"
            )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument(
        "--restore-to", type=Path, help="Copy a verified archive into a new, nonexistent directory"
    )
    args = parser.parse_args()
    try:
        result = (
            restore_backup(args.backup, args.restore_to) if args.restore_to else verify_backup(args.backup)
        )
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.exit(1, f"Backup verification/restore failed: {exc}\n")
    print(json.dumps(result, indent=2))
    if args.restore_to:
        print(
            "Restored into new directory. Set STRATOS_DATA_DIR to that directory before starting API and worker."
        )


if __name__ == "__main__":
    main()
