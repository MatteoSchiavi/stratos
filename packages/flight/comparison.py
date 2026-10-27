"""Time-aligned comparison of saved predictions; no new weather or integration."""

from datetime import UTC, datetime, timedelta

import numpy as np
from geographiclib.geodesic import Geodesic

from packages.domain.models import ComparisonRequest, digest


def configuration_differences(left: dict, right: dict, prefix: str = "") -> list[dict]:
    differences = []
    for key in sorted(set(left) | set(right)):
        name = f"{prefix}.{key}" if prefix else key
        a, b = left.get(key), right.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            differences.extend(configuration_differences(a, b, name))
        elif a != b:
            differences.append({"field": name, "reference": a, "candidate": b})
    return differences


class SavedPath:
    def __init__(self, run: dict):
        self.rows = run["samples"]
        if not 2 <= len(self.rows) <= 20000:
            raise ValueError("Comparison needs2–20000 saved samples per study")
        self.elapsed = np.array([p["elapsed_s"] for p in self.rows], dtype=float)
        self.positions = np.array(
            [[p["latitude_deg"], p["longitude_deg"], p["geometric_msl_m"]] for p in self.rows], dtype=float
        )
        self.start = datetime.fromisoformat(run["manifest"]["config"]["launch"]["start_utc"])
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("Saved launch time must have an explicit UTC offset")
        if (
            not np.all(np.isfinite(self.elapsed))
            or not np.all(np.isfinite(self.positions))
            or self.elapsed[0] != 0
            or not np.all(np.diff(self.elapsed) > 0)
            or np.any(np.abs(self.positions[:, 0]) > 89.5)
            or np.any(np.abs(self.positions[:, 1]) > 180)
        ):
            raise ValueError("Saved coordinates/times are invalid or not strictly increasing")
        for row, elapsed in zip(self.rows, self.elapsed, strict=True):
            stamp = datetime.fromisoformat(row["time_utc"])
            if (
                stamp.tzinfo is None
                or stamp.utcoffset() is None
                or abs((stamp - self.start).total_seconds() - elapsed) > 1e-5
            ):
                raise ValueError("Saved sample UTC and elapsed time disagree")
        self.lines: dict[int, dict] = {}

    def at(self, elapsed: float) -> dict:
        if elapsed < self.elapsed[0] - 1e-6 or elapsed > self.elapsed[-1] + 1e-6:
            raise ValueError("Comparison would extrapolate outside saved samples")
        elapsed = float(np.clip(elapsed, self.elapsed[0], self.elapsed[-1]))
        i = min(max(int(np.searchsorted(self.elapsed, elapsed, side="right")) - 1, 0), len(self.rows) - 2)
        fraction = (elapsed - self.elapsed[i]) / (self.elapsed[i + 1] - self.elapsed[i])
        a, b = self.positions[i], self.positions[i + 1]
        if fraction == 0:
            lat, lon = a[:2]
        elif fraction == 1:
            lat, lon = b[:2]
        else:
            if i not in self.lines:
                self.lines[i] = Geodesic.WGS84.Inverse(*a[:2], *b[:2])
            segment = self.lines[i]
            point = Geodesic.WGS84.Direct(*a[:2], segment["azi1"], segment["s12"] * fraction)
            lat, lon = point["lat2"], point["lon2"]
        return {
            "time_utc": (self.start + timedelta(seconds=float(elapsed))).astimezone(UTC).isoformat(),
            "elapsed_s": float(elapsed),
            "latitude_deg": float(lat),
            "longitude_deg": float(lon),
            "geometric_msl_m": float(a[2] + fraction * (b[2] - a[2])),
        }


def compare_runs(reference: dict, candidate: dict, request: ComparisonRequest) -> dict:
    if reference["id"] != str(request.reference_id) or candidate["id"] != str(request.candidate_id):
        raise ValueError("Comparison request and supplied saved-study identifiers disagree")
    left, right = SavedPath(reference), SavedPath(candidate)
    delta = (right.start - left.start).total_seconds()
    # Work in relative seconds to preserve precision; UTC alignment is a shift
    # by the source launch-time difference, not arithmetic on Unix epoch floats.
    if request.alignment == "utc":
        begin, end = max(0.0, delta), min(float(left.elapsed[-1]), delta + float(right.elapsed[-1]))
    else:
        begin, end = 0.0, min(float(left.elapsed[-1]), float(right.elapsed[-1]))
    if end <= begin:
        raise ValueError("Saved studies have no positive shared time interval under this alignment")
    points = []
    for elapsed in np.linspace(begin, end, request.sample_count):
        a = left.at(float(elapsed))
        b = right.at(float(elapsed - delta) if request.alignment == "utc" else float(elapsed))
        separation = Geodesic.WGS84.Inverse(
            a["latitude_deg"], a["longitude_deg"], b["latitude_deg"], b["longitude_deg"]
        )["s12"]
        points.append(
            {
                "comparison_elapsed_s": float(elapsed - begin),
                "reference": a,
                "candidate": b,
                "horizontal_separation_m": float(separation),
                "height_difference_m": b["geometric_msl_m"] - a["geometric_msl_m"],
            }
        )
    separations = [p["horizontal_separation_m"] for p in points]
    maximum = int(np.argmax(separations))
    sources = []
    for run in (reference, candidate):
        sources.append(
            {
                "id": run["id"],
                "name": run["name"],
                "weather_provider": run["weather_provider"],
                "weather_run_utc": run["manifest"]["weather"].get("run_utc"),
                "forecast_dataset_id": run["manifest"]["weather"].get("id"),
                "solver_version": run.get("solver_version", "legacy-surface-v1"),
                "config_sha256": run["manifest"]["config_sha256"],
                "output_sha256": run["manifest"]["output_sha256"],
                "manifest_sha256": run["manifest"]["sha256"],
                "saved_sample_count": len(run["samples"]),
            }
        )
    result = {
        "schema_version": 1,
        "procedure": "saved-wgs84-geodesic-alignment-v1",
        "request": request.model_dump(mode="json"),
        "sources": sources,
        "alignment": request.alignment,
        "alignment_description": "Equal elapsed time since each launch; UTC instants may differ"
        if request.alignment == "elapsed"
        else "Equal absolute UTC within the shared source horizon",
        "duration_s": end - begin,
        "sample_count": len(points),
        "shared_window": {
            "reference_start_utc": points[0]["reference"]["time_utc"],
            "reference_end_utc": points[-1]["reference"]["time_utc"],
            "candidate_start_utc": points[0]["candidate"]["time_utc"],
            "candidate_end_utc": points[-1]["candidate"]["time_utc"],
        },
        "metrics": {
            "maximum_sampled_separation_m": max(separations),
            "mean_sampled_separation_m": float(np.mean(separations)),
            "shared_window_end_separation_m": separations[-1],
            "maximum_absolute_sampled_height_difference_m": max(
                abs(p["height_difference_m"]) for p in points
            ),
            "maximum_separation_sample_index": maximum,
        },
        "configuration_differences": configuration_differences(
            reference["manifest"]["config"], candidate["manifest"]["config"]
        ),
        "points": points,
        "quality": "comparison_of_uncalibrated_predictions",
        "limitations": [
            "Two modeled predictions; separation is scenario sensitivity, not observed forecast error or launch reliability.",
            "Positions interpolate along shortest WGS84 geodesics between saved snapshots; geometric MSL height interpolates linearly.",
            "Statistics cover the bounded shared interval and requested sample grid, not unsampled global extrema.",
            "Different solver versions/weather providers are retained explicitly; no resimulation, weather download or calibrated probability is performed.",
        ],
    }
    return {**result, "comparison_sha256": digest(result)}
