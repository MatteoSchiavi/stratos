"""Reproduce retained real NOAA examples without network access."""

import json
from pathlib import Path

from packages.domain.models import MissionConfig, digest
from packages.flight.integrator import simulate
from packages.meteo.gfs import open_cached
from services.api.storage import ROOT


def reproduce(example: Path) -> dict:
    expected = json.loads(example.read_text())
    manifest = expected["manifest"]
    assert digest({k: v for k, v in manifest.items() if k != "sha256"}) == manifest["sha256"]
    config = MissionConfig.model_validate(manifest["config"])
    assert config.revision_hash == manifest["config_sha256"]
    field = open_cached(
        ROOT / "tests/fixtures/noaa-gfs-20261027-06-regional",
        legacy_surface_boundary=config.schema_version == 1,
    )
    result = simulate(config, field)
    same_hash = digest(result) == manifest["output_sha256"]
    assert len(result["samples"]) == len(expected["samples"])
    max_coordinate_error_deg = max(
        abs(a[key] - b[key])
        for a, b in zip(result["samples"], expected["samples"], strict=True)
        for key in ("latitude_deg", "longitude_deg")
    )
    assert max_coordinate_error_deg < 1e-9
    assert abs(result["distance_m"] - expected["distance_m"]) < 1e-4
    return {
        "example": example.name,
        "provider": field.provenance["provider"],
        "run_utc": field.provenance["run_utc"],
        "samples": len(result["samples"]),
        "distance_m": result["distance_m"],
        "duration_s": result["duration_s"],
        "recomputed_output_sha256": digest(result),
        "exact_output_hash_equal": same_hash,
        "max_coordinate_error_deg": max_coordinate_error_deg,
        "cross_platform_note": "Exact hashes are reported; acceptance tolerance allows minor platform floating-point differences",
    }


if __name__ == "__main__":
    for name in ("noaa-simulation.json", "noaa-ascent-simulation.json"):
        print(json.dumps(reproduce(ROOT / "docs/examples" / name), indent=2))
