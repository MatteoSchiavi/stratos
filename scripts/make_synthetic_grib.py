"""Generate tiny, explicitly SYNTHETIC GRIB2 decoder fixtures; never NOAA observations.

Run from repository root: .venv/bin/python -m scripts.make_synthetic_grib
"""

from datetime import UTC, datetime
from pathlib import Path

import eccodes as ec
import numpy as np

from packages.domain.models import digest
from packages.meteo.gfs import LEVELS_HPA, atomic_json, sha256_file


def make(path: Path, lead: int, omit: tuple | None = None):
    fields = [
        ("isobaricInhPa", level, name, value)
        for level in LEVELS_HPA
        for name, value in [
            ("u", 12),
            ("v", 3),
            ("t", 250),
            ("gh", 44330 * (1 - (level * 100 / 101325) ** 0.190263)),
        ]
    ]
    fields.extend(
        [
            ("surface", 0, "gh", 0),
            ("surface", 0, "sp", 101325),
            ("heightAboveGround", 10, "10u", 12),
            ("heightAboveGround", 10, "10v", 3),
            ("heightAboveGround", 2, "2t", 288.15),
        ]
    )
    with path.open("wb") as stream:
        for kind, level, name, value in fields:
            if (kind, level, name) == omit:
                continue
            h = ec.codes_grib_new_from_samples("regular_ll_pl_grib2")
            try:
                for key, val in {
                    "centre": "kwbc",
                    "dataDate": 20261027,
                    "dataTime": 0,
                    "forecastTime": lead,
                    "Ni": 2,
                    "Nj": 2,
                    "latitudeOfFirstGridPointInDegrees": 45.25,
                    "latitudeOfLastGridPointInDegrees": 45,
                    "longitudeOfFirstGridPointInDegrees": 9,
                    "longitudeOfLastGridPointInDegrees": 9.25,
                    "iDirectionIncrementInDegrees": 0.25,
                    "jDirectionIncrementInDegrees": 0.25,
                    "typeOfLevel": kind,
                    "level": level,
                    "shortName": name,
                }.items():
                    ec.codes_set(h, key, val)
                ec.codes_set_values(h, np.full(4, value))
                ec.codes_write(h, stream)
            finally:
                ec.codes_release(h)


if __name__ == "__main__":
    directory = Path("tests/fixtures")
    records = []
    for lead in (0, 1):
        path = directory / f"synthetic-gfs-shaped-f{lead:03d}.grib2"
        make(path, lead)
        records.append({"file": path.name, "sha256": sha256_file(path), "lead_hour": lead})
    manifest = {
        "origin": "demo",
        "provider": "SYNTHETIC",
        "licence": "Generated project test data",
        "source": "scripts/make_synthetic_grib.py using ecCodes samples, not downloaded NOAA data",
        "run_utc": datetime(2026, 10, 27, tzinfo=UTC).isoformat(),
        "files": records,
        "u_ms": 12,
        "v_ms": 3,
        "height_model": "ISA approximation, deliberately synthetic",
    }
    manifest["sha256"] = digest(manifest)
    atomic_json(directory / "synthetic-grib-provenance.json", manifest)
    print("Generated and hashed SYNTHETIC GRIB2 decoder fixtures")
