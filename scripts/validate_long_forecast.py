"""Bounded real-GFS endurance check, with a measurable address-space/RSS budget on Linux."""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from packages.domain.models import ExpansionPolicy, MissionConfig, digest
from packages.flight.integrator import simulate
from packages.meteo.adaptive import AdaptiveField
from packages.meteo.gfs import atomic_json, fetch_subset, open_cached, read_manifest, sha256_file
from services.api.provenance import assert_runtime_unchanged, code_identity
from services.api.storage import DATA


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--start", default="2026-10-27T16:00:00+00:00")
    parser.add_argument("--hours", type=float, default=48)
    parser.add_argument(
        "--offline", action="store_true", help="Require already cached exact crops; make no network requests"
    )
    parser.add_argument("--output", type=Path, default=DATA / "review48-result.json")
    args = parser.parse_args()
    if sys.platform != "linux":
        raise SystemExit(
            "This resource-qualification procedure is Linux-only; RSS units/limits are not qualified on this platform"
        )
    import resource

    # Imports are already loaded, so the cap includes their virtual mappings.
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
    loaded_code = code_identity()
    c = MissionConfig()
    c.launch.start_utc = datetime.fromisoformat(args.start)
    c.flight.initial_geometric_m = c.flight.target_geometric_m = 12500
    c.flight.float_duration_hours = args.hours
    c.weather.provider = "NOAA_GFS"
    c.weather.dataset_id = args.dataset
    # Direct edits to a mutable Pydantic model do not validate assignment. Use
    # the same normalized numeric types as the HTTP/revision workflow before
    # calculating and hashing an ostensibly identical replay.
    c = MissionConfig.model_validate(c.model_dump(mode="json"))
    initial = open_cached(DATA / "cache" / args.dataset, at_time=c.launch.start_utc)
    started = time.monotonic()
    last = [-1]

    def cancelled():
        if time.monotonic() - started > 900:
            raise TimeoutError("Endurance check exceeded 15-minute cap")
        return False

    def progress(f, message="Integrating"):
        if int(f * 10) != last[0] or message != "Integrating":
            print(f"{f * 100:.1f}% {message}", flush=True)
            last[0] = int(f * 10)

    def offline_fetch(request, cache, *_, **__):
        ident = "gfs_" + digest(request.model_dump(mode="json"))[:24]
        manifest = read_manifest(cache / ident)
        for record in manifest["files"]:
            if sha256_file(cache / ident / record["file"]) != record["sha256"]:
                raise ValueError("Offline crop checksum mismatch; no network repair attempted")
        return manifest

    weather = AdaptiveField(
        initial,
        DATA / "cache",
        ExpansionPolicy(max_tiles=16, max_download_mib=128),
        progress,
        cancelled,
        fetcher=offline_fetch if args.offline else fetch_subset,
    )
    try:
        output = simulate(c, weather, progress, cancelled)
        assert_runtime_unchanged(loaded_code)
        report = {
            "schema_version": 2,
            "config": c.model_dump(mode="json"),
            "output": output,
            "output_sha256": digest(output),
            "weather": weather.provenance,
            "elapsed_wall_s": time.monotonic() - started,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "address_space_limit_bytes": 6 * 1024**3,
            "code": loaded_code,
            "procedure_sha256": sha256_file(Path(__file__)),
            "network_disabled_by_test": args.offline,
            "limitations": [
                "This is a process-budget test on Linux, not a native 8GB-host or Windows qualification.",
                "Deterministic uncalibrated L0 transport; forecast skill is not measured.",
            ],
        }
        atomic_json(args.output, report)
        print(
            f"COMPLETED {output['distance_m'] / 1000:.3f} km; peak RSS {report['peak_rss_kib'] / 1024:.1f} MiB; {weather.provenance['segment_count']} weather segments",
            flush=True,
        )
    except Exception as exc:
        atomic_json(
            args.output.with_suffix(".failed.json"),
            {"error": str(exc), "weather": weather.provenance, "elapsed_wall_s": time.monotonic() - started},
        )
        raise


if __name__ == "__main__":
    main()
