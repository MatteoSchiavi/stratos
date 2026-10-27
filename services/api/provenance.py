import hashlib
import importlib.metadata
import platform
import subprocess
from pathlib import Path

from packages.meteo.gfs import sha256_file
from services.api.storage import ROOT


def code_identity() -> dict:
    paths: list[Path] = []
    for directory in ("packages", "services", "apps/web/src"):
        paths.extend(p for p in (ROOT / directory).rglob("*") if p.suffix in (".py", ".ts", ".tsx", ".css"))
    paths.extend(ROOT / p for p in ("pyproject.toml", "uv.lock", "apps/web/package-lock.json"))
    checksums = {str(p.relative_to(ROOT)): sha256_file(p) for p in sorted(paths) if p.is_file()}
    from packages.domain.models import canonical

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except subprocess.CalledProcessError:
        commit = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_commit": commit,
        "source_files_sha256": checksums,
        "source_tree_sha256": hashlib.sha256(canonical(checksums)).hexdigest(),
        "scientific_source_sha256": hashlib.sha256(
            canonical(
                {
                    k: v
                    for k, v in checksums.items()
                    if k.endswith(".py") or k in ("pyproject.toml", "uv.lock")
                }
            )
        ).hexdigest(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "numpy",
                "scipy",
                "geographiclib",
                "xarray",
                "cfgrib",
                "eccodes",
                "fastapi",
                "pydantic",
            )
        },
    }


def assert_runtime_unchanged(loaded: dict, current: dict | None = None):
    current = current or code_identity()
    if (
        current["scientific_source_sha256"] != loaded["scientific_source_sha256"]
        or current["packages"] != loaded["packages"]
    ):
        raise ValueError(
            "Scientific code or dependencies changed after worker startup; restart the API/worker before running or publishing results"
        )
