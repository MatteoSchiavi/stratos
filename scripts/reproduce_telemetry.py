"""Offline protocol/archive/recovery evidence; optional bounded72h synthetic stress study."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from packages.domain.models import digest
from packages.telemetry.archive import canonical_records, decode_archive, encode_archive, scientific_summary
from packages.telemetry.codec import decode, encode
from packages.telemetry.examples import example_study
from packages.telemetry.models import Observation, RecoveryRequest
from packages.telemetry.recovery import simulate_recovery
from services.api.provenance import code_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New directory; existing paths are never overwritten")
    parser.add_argument(
        "--long",
        action="store_true",
        help="Synthetic72h scheduling stress case, not NOAA/flight qualification",
    )
    args = parser.parse_args()
    config = example_study()
    if args.long:
        values = config.model_dump()
        values.update(duration_s=259200, step_s=10, sample_interval_s=60)
        values["positions"] = [
            Observation(
                time_s=t,
                sequence=i,
                latitude_deg=45,
                longitude_deg=9.7,
                altitude_m=12500,
                temperature_k=225,
                pressure_pa=18000,
                origin="simulated",
            ).model_dump()
            for i, t in enumerate(range(0, 259201, 300))
        ]
        values["profiles"][0]["end_s"] = 259200
        values["contacts"] = [dict(values["contacts"][0], start_s=86400, end_s=259200)]
        values["outages"] = []
        config = RecoveryRequest.model_validate(values)
    start = time.monotonic()
    output = simulate_recovery(config)
    seconds = time.monotonic() - start
    raw = encode_archive(config.positions, config.epoch_utc.isoformat())
    assert canonical_records(decode_archive(raw)) == canonical_records(config.positions)
    vectors = []
    for family in ("NAV", "NAV+ENV", "HISTORY", "EMERGENCY"):
        rows = config.positions[:4] if family == "HISTORY" else config.positions[:1]
        packet = encode(family, rows)
        vectors.append({"family": family, "hex": packet.hex(), "decoded": decode(packet)})
    try:
        import resource

        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        peak_rss = None
    report = {
        "scenario": "synthetic72h_stress" if args.long else "explicitly_synthetic_contact_scenario",
        "configuration_sha256": digest(config.model_dump(mode="json")),
        "output_sha256": digest(output),
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "archive_bytes": len(raw),
        "round_trip_verified": True,
        "wall_seconds": seconds,
        "peak_rss_native_units": peak_rss,
        "rss_units_note": "KiB on Linux; bytes on macOS. Same-host measurement, not independent8GB qualification.",
        "metrics": output["metrics"],
        "freshness": output["freshness"],
        "code": code_identity(),
    }
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)

        def save(name, value):
            (args.output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")

        save("configuration.json", config.model_dump(mode="json"))
        save("recovery.json", output)
        save("wire-vectors.json", vectors)
        save("lossy-summary.json", scientific_summary(config.positions))
        save("verification.json", report)
        (args.output / "observations.stla").write_bytes(raw)
    print(json.dumps({k: v for k, v in report.items() if k != "code"}, indent=2))


if __name__ == "__main__":
    main()
