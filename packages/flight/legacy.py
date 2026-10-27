"""Fourth-order wind integration in Earth-centred coordinates with WGS84 retraction.

Each RK stage retracts to the geodetic surface; winds are transformed from the
local ENU basis into ECEF. This avoids longitude's pole/dateline singularity.
Altitude is prescribed and has no effect on the WGS84 horizontal reference surface.
"""

import math
from datetime import timedelta
from typing import Callable

import numpy as np
from geographiclib.geodesic import Geodesic

from packages.domain.models import Cancelled, MissionConfig
from packages.meteo.field import WeatherField

A = 6_378_137.0
B = 6_356_752.314245179
E2 = 1 - (B / A) ** 2


def to_ecef(lat: float, lon: float) -> np.ndarray:
    phi, lam = np.radians([lat, lon])
    n = A / np.sqrt(1 - E2 * np.sin(phi) ** 2)
    return np.array(
        [n * np.cos(phi) * np.cos(lam), n * np.cos(phi) * np.sin(lam), n * (1 - E2) * np.sin(phi)]
    )


def to_latlon(position) -> tuple[float, float]:
    # Radial retraction to WGS84: geodetic latitude from ellipsoid normal.
    x, y, z = position
    return math.degrees(math.atan2(z * A * A, math.hypot(x, y) * B * B)), math.degrees(math.atan2(y, x))


def profile(config: MissionConfig, elapsed: float) -> tuple[float, float, str]:
    f = config.flight
    ascent_end = (f.target_geometric_m - f.initial_geometric_m) / f.ascent_ms
    float_end = ascent_end + f.float_duration_hours * 3600
    if elapsed < ascent_end - 1e-7:
        return f.initial_geometric_m + elapsed * f.ascent_ms, f.ascent_ms, "ASCENT"
    if elapsed < float_end - 1e-7 or f.descent_ms is None:
        return f.target_geometric_m, 0, "FLOAT"
    alt = max(config.launch.ground_geometric_m, f.target_geometric_m - (elapsed - float_end) * f.descent_ms)
    return (
        alt,
        -f.descent_ms if alt > config.launch.ground_geometric_m else 0,
        ("DESCENT" if alt > config.launch.ground_geometric_m else "GROUND_PLANE"),
    )


def simulate(
    config: MissionConfig,
    weather: WeatherField,
    progress: Callable[[float], None] = lambda _: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict:
    f = config.flight
    ascent_end = (f.target_geometric_m - f.initial_geometric_m) / f.ascent_ms
    float_end = ascent_end + f.float_duration_hours * 3600
    end = float_end + (
        (f.target_geometric_m - config.launch.ground_geometric_m) / f.descent_ms if f.descent_ms else 0
    )
    if end > 72 * 3600:
        raise ValueError("Total prescribed profile exceeds the P1 72-hour compute bound")
    launch = config.launch
    position = to_ecef(launch.latitude_deg, launch.longitude_deg)
    elapsed = 0.0
    rows: list[dict] = []
    distance = 0.0

    def velocity(pos, t):
        lat, lon = to_latlon(pos)
        alt, _, _ = profile(config, t)
        state = weather.get_state(lat, lon, alt, launch.start_utc + timedelta(seconds=t))
        phi, lam = np.radians([lat, lon])
        east = np.array([-np.sin(lam), np.cos(lam), 0])
        north = np.array([-np.sin(phi) * np.cos(lam), -np.sin(phi) * np.sin(lam), np.cos(phi)])
        return state.u_ms * east + state.v_ms * north

    def snapshot():
        nonlocal distance
        lat, lon = to_latlon(position)
        alt, vertical, phase = profile(config, elapsed)
        time = launch.start_utc + timedelta(seconds=elapsed)
        state = weather.get_state(lat, lon, alt, time)
        if rows:
            distance += Geodesic.WGS84.Inverse(rows[-1]["latitude_deg"], rows[-1]["longitude_deg"], lat, lon)[
                "s12"
            ]
        rows.append(
            {
                "time_utc": time.isoformat(),
                "elapsed_s": elapsed,
                "latitude_deg": lat,
                "longitude_deg": lon,
                "geometric_msl_m": alt,
                "geopotential_m": state.geopotential_m,
                "vertical_ms": vertical,
                "phase": phase,
                "u_ms": state.u_ms,
                "v_ms": state.v_ms,
                "speed_ms": math.hypot(state.u_ms, state.v_ms),
                "temperature_k": state.temperature_k,
                "pressure_pa": state.pressure_pa,
                "distance_m": distance,
                "weather_before_utc": state.valid_before_utc,
                "weather_after_utc": state.valid_after_utc,
                "weather_time_weight": state.temporal_weight,
                "member": "deterministic",
                "origin": "demo" if weather.provenance["provider"] == "SYNTHETIC" else "derived",
                "quality": "modeled_uncalibrated",
            }
        )

    snapshot()
    next_sample = float(f.sample_interval_s)
    while elapsed < end - 1e-7:
        if cancelled():
            raise Cancelled("Simulation cancelled; no finalized prediction was saved")
        future_events = [v for v in (ascent_end, float_end, end, next_sample) if v > elapsed + 1e-7]
        step = min(float(f.integration_step_s), min(future_events) - elapsed)
        k1 = velocity(position, elapsed)
        k2 = velocity(position + step * k1 / 2, elapsed + step / 2)
        k3 = velocity(position + step * k2 / 2, elapsed + step / 2)
        k4 = velocity(position + step * k3, elapsed + step)
        position = to_ecef(*to_latlon(position + step * (k1 + 2 * k2 + 2 * k3 + k4) / 6))
        elapsed += step
        if any(abs(elapsed - v) < 1e-6 for v in (ascent_end, float_end, end, next_sample)):
            snapshot()
            progress(elapsed / end)
        if elapsed >= next_sample - 1e-7:
            next_sample += f.sample_interval_s
    return {
        "samples": rows,
        "distance_m": distance,
        "duration_s": end,
        "termination": "configured_ground_plane" if f.descent_ms else "prescribed_float_end",
        "model": "L0_prescribed",
        "quality": "modeled_uncalibrated",
        "limitations": [
            "Prescribed altitude: lift, envelope leakage, burst and survival are not modeled.",
            "Deterministic track; no calibrated uncertainty or mission-success probability.",
            "No radio, data recovery or energy model is implemented in this phase.",
            "Descent, if enabled, ends at configured flat ground, not mapped terrain.",
            "Horizontal transport uses winds on the WGS84 surface; altitude curvature correction is omitted (<0.32% at 20 km).",
        ],
    }
