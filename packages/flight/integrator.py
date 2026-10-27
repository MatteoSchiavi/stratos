"""Versioned L0 transport on WGS84 with prescribed geometric MSL height.

Schema 1 retains the original reference-surface solver for reproducibility.
Schema 2 integrates the exact geodetic curvature rates at the prescribed height.
"""

import math
from datetime import timedelta
from typing import Callable

import numpy as np
from geographiclib.geodesic import Geodesic

from packages.domain.models import Cancelled, MissionConfig
from packages.flight.legacy import profile
from packages.flight.legacy import simulate as simulate_legacy
from packages.meteo.field import WeatherDomainError, WeatherField

A = 6_378_137.0
E2 = 6.6943799901413165e-3


def curvature_radii(latitude_rad: float) -> tuple[float, float]:
    denominator = 1 - E2 * math.sin(latitude_rad) ** 2
    return A * (1 - E2) / denominator**1.5, A / math.sqrt(denominator)


def simulate(
    config: MissionConfig,
    weather: WeatherField,
    progress: Callable[[float], None] = lambda _: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict:
    if config.schema_version == 1:
        return simulate_legacy(config, weather, progress, cancelled)
    f, launch = config.flight, config.launch
    ascent_end = (f.target_geometric_m - f.initial_geometric_m) / f.ascent_ms
    float_end = ascent_end + f.float_duration_hours * 3600
    end = float_end + (
        (f.target_geometric_m - launch.ground_geometric_m) / f.descent_ms if f.descent_ms else 0
    )
    if end > 72 * 3600:
        raise ValueError("Total prescribed profile exceeds the 72-hour compute bound")
    # latitude/longitude are radians; air distance is an independently integrated state.
    state = np.array([math.radians(launch.latitude_deg), math.radians(launch.longitude_deg), 0.0])
    elapsed, ground_distance = 0.0, 0.0
    rows: list[dict] = []

    def sample_weather(position, t):
        phi, lam = float(position[0]), float(position[1])
        lat, lon = math.degrees(phi), (math.degrees(lam) + 180) % 360 - 180
        if abs(lat) > 89.5:
            raise WeatherDomainError("Trajectory reached unsupported polar wind basis beyond 89.5 degrees")
        height, _, _ = profile(config, t)
        return lat, lon, height, weather.get_state(lat, lon, height, launch.start_utc + timedelta(seconds=t))

    def derivative(position, t):
        _, _, height, wind = sample_weather(position, t)
        meridional, prime_vertical = curvature_radii(float(position[0]))
        return np.array(
            [
                wind.v_ms / (meridional + height),
                wind.u_ms / ((prime_vertical + height) * math.cos(float(position[0]))),
                math.hypot(wind.u_ms, wind.v_ms),
            ]
        )

    def snapshot():
        lat, lon, altitude, wind = sample_weather(state, elapsed)
        _, vertical, phase = profile(config, elapsed)
        rows.append(
            {
                "time_utc": (launch.start_utc + timedelta(seconds=elapsed)).isoformat(),
                "elapsed_s": elapsed,
                "latitude_deg": lat,
                "longitude_deg": lon,
                "geometric_msl_m": altitude,
                "geopotential_m": wind.geopotential_m,
                "vertical_ms": vertical,
                "phase": phase,
                "u_ms": wind.u_ms,
                "v_ms": wind.v_ms,
                "speed_ms": math.hypot(wind.u_ms, wind.v_ms),
                "temperature_k": wind.temperature_k,
                "pressure_pa": wind.pressure_pa,
                "distance_m": ground_distance,
                "horizontal_air_distance_m": float(state[2]),
                "weather_before_utc": wind.valid_before_utc,
                "weather_after_utc": wind.valid_after_utc,
                "weather_time_weight": wind.temporal_weight,
                "weather_dataset_id": wind.dataset_id,
                "member": "deterministic",
                "origin": "demo" if weather.provenance["provider"] == "SYNTHETIC" else "derived",
                "quality": "modeled_uncalibrated",
            }
        )

    snapshot()
    # Output cadence must not alter the numerical mesh or path-length calculation.
    next_output = float(f.sample_interval_s)
    # Integrate a canonical mesh independent of output frequency, then use RK4
    # dense re-evaluation from each step's beginning for requested sample times.
    while elapsed < end - 1e-7:
        if cancelled():
            raise Cancelled("Simulation cancelled; no finalized prediction was saved")
        future_events = [v for v in (ascent_end, float_end, end) if v > elapsed + 1e-7]
        step = min(float(f.integration_step_s), min(future_events) - elapsed)
        previous = state.copy()
        previous_t, previous_distance = elapsed, ground_distance

        def advance(h, previous=previous, previous_t=previous_t):
            k1 = derivative(previous, previous_t)
            k2 = derivative(previous + h * k1 / 2, previous_t + h / 2)
            k3 = derivative(previous + h * k2 / 2, previous_t + h / 2)
            k4 = derivative(previous + h * k3, previous_t + h)
            return previous + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6

        next_state = advance(step)
        a_lat, a_lon = map(math.degrees, previous[:2])
        b_lat, b_lon = map(math.degrees, next_state[:2])
        step_distance = Geodesic.WGS84.Inverse(a_lat, a_lon, b_lat, b_lon)["s12"]
        # The progress callback and cancellation checks run every canonical step.
        while next_output < previous_t + step - 1e-7:
            if next_output > previous_t + 1e-7:
                partial = advance(next_output - previous_t)
                p_lat, p_lon = map(math.degrees, partial[:2])
                state, elapsed = partial, next_output
                ground_distance = (
                    previous_distance + Geodesic.WGS84.Inverse(a_lat, a_lon, p_lat, p_lon)["s12"]
                )
                snapshot()
            next_output += f.sample_interval_s
        state, elapsed = next_state, previous_t + step
        ground_distance = previous_distance + step_distance
        at_output = abs(elapsed - next_output) < 1e-6
        if at_output or any(abs(elapsed - v) < 1e-6 for v in (ascent_end, float_end, end)):
            snapshot()
        if at_output:
            next_output += f.sample_interval_s
        progress(min(elapsed / end, 1.0))
    return {
        "samples": rows,
        "distance_m": ground_distance,
        "horizontal_air_distance_m": float(state[2]),
        "duration_s": end,
        "termination": "configured_ground_plane" if f.descent_ms else "prescribed_float_end",
        "model": "L0_prescribed",
        "solver_version": "wgs84-height-rk4-v2",
        "quality": "modeled_uncalibrated",
        "limitations": [
            "Prescribed altitude: lift, envelope leakage, burst and survival are not modeled.",
            "Deterministic track; no calibrated uncertainty or mission-success probability.",
            "No radio, data recovery or energy model is implemented in this phase.",
            "Descent, if enabled, ends at configured flat ground, not mapped terrain.",
            "WGS84 curvature includes geometric MSL height; a precise local geoid model is not supplied.",
            "Ground-track distance is accumulated on integration steps; horizontal air distance is separate.",
        ],
    }
