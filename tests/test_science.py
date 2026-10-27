from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from geographiclib.geodesic import Geodesic

from packages.domain.models import MissionConfig
from packages.flight.integrator import simulate
from packages.meteo.field import GridField, SyntheticField, WeatherDomainError, geometric_m, geopotential_m

START = datetime(2026, 10, 27, 12, tzinfo=UTC)


def mission(**changes):
    config = MissionConfig().model_dump(mode="json")
    config["schema_version"] = 1  # Keep the original solver reference vectors.
    config["launch"].update(latitude_deg=0, longitude_deg=0, ground_geometric_m=0)
    config["flight"].update(
        initial_geometric_m=1000,
        target_geometric_m=1000,
        float_duration_hours=1,
        sample_interval_s=60,
        **changes,
    )
    return MissionConfig.model_validate(config)


def test_no_wind_stationary():
    result = simulate(mission(), SyntheticField(0, 0))
    assert len(result["samples"]) == 61
    assert result["distance_m"] == pytest.approx(0, abs=1e-6)
    assert result["samples"][-1]["elapsed_s"] == 3600


@pytest.mark.parametrize("lat,lon,u,v", [(0, 0, 20, 0), (45, 9, 0, 10), (80, 179.9, 0, 10)])
def test_constant_wind_against_independent_geodesic(lat, lon, u, v):
    config = mission()
    config.launch.latitude_deg, config.launch.longitude_deg = lat, lon
    result = simulate(config, SyntheticField(u, v))
    expected = Geodesic.WGS84.Direct(lat, lon, 90 if u else 0, (u + v) * 3600)
    end = result["samples"][-1]
    error = Geodesic.WGS84.Inverse(
        end["latitude_deg"], end["longitude_deg"], expected["lat2"], expected["lon2"]
    )["s12"]
    assert error < 0.02
    assert result["distance_m"] == pytest.approx((u + v) * 3600, abs=0.02)


def test_dateline_and_high_latitude_transport():
    config = mission()
    config.launch.latitude_deg, config.launch.longitude_deg = 85, 179.9
    result = simulate(config, SyntheticField(20, 0))
    assert result["samples"][-1]["longitude_deg"] < 0
    assert all(-180 <= p["longitude_deg"] <= 180 for p in result["samples"])
    assert result["distance_m"] == pytest.approx(72000, abs=1)


def test_vertical_events_and_configured_ground():
    config = mission()
    config.flight.initial_geometric_m = 0
    config.flight.target_geometric_m = 120
    config.flight.ascent_ms = 2
    config.flight.float_duration_hours = 1 / 60
    config.flight.descent_ms = 2
    result = simulate(config, SyntheticField(0, 0))
    assert result["duration_s"] == 180
    points = {p["elapsed_s"]: p for p in result["samples"]}
    assert points[0]["phase"] == "ASCENT"
    assert points[60]["phase"] == "FLOAT"
    assert points[120]["phase"] == "DESCENT"
    assert points[180]["phase"] == "GROUND_PLANE"
    assert points[180]["geometric_msl_m"] == 0


def grid(*, lons=(0, 1), missing=False, timegap=3600):
    times = np.array([START.timestamp(), START.timestamp() + timegap])
    lats = np.array([40, 41])
    pressures = np.array([100000, 50000, 20000])
    shape = (2, 3, 2, len(lons))
    h = np.broadcast_to(np.array([0, 5000, 12000])[None, :, None, None], shape).copy()
    u = np.empty(shape)
    for t in range(2):
        for j, lat in enumerate(lats):
            for k, lon in enumerate(lons):
                u[t, :, j, k] = t * 4 + (lat - 40) * 2 + (lon - lons[0]) + h[t, :, j, k] / 1000
    if missing:
        u[0, 1, 0, 0] = np.nan
    return GridField(
        times,
        lats,
        lons,
        pressures,
        u,
        u * 0,
        u * 0 + 250,
        h,
        {"provider": "SYNTHETIC", "run_utc": START.isoformat()},
    )


def test_space_time_height_and_log_pressure_analytic():
    state = grid().get_state(40.5, 0.5, geometric_m(2500), START + timedelta(minutes=30))
    assert state.u_ms == pytest.approx(2 + 1 + 0.5 + 2.5)
    assert state.pressure_pa == pytest.approx(np.sqrt(100000 * 50000))
    assert state.temporal_weight == 0.5


def test_grid_dateline_wrap():
    state = grid(lons=(170, 180, 190)).get_state(40, -175, geometric_m(1000), START)
    assert state.u_ms == pytest.approx(16)


@pytest.mark.parametrize(
    "lat,lon,z,seconds",
    [
        (39, 0, 1000, 0),
        (40, 3, 1000, 0),
        (40, 0, -1, 0),
        (40, 0, 15000, 0),
        (40, 0, 1000, -1),
        (40, 0, 1000, 3601),
    ],
)
def test_no_unsupported_extrapolation(lat, lon, z, seconds):
    with pytest.raises(WeatherDomainError):
        grid().get_state(lat, lon, z, START + timedelta(seconds=seconds))


def test_missing_cells_and_hourly_leads_rejected():
    with pytest.raises(WeatherDomainError, match="NaN"):
        grid(missing=True).get_state(40.5, 0.5, 1000, START)
    with pytest.raises(WeatherDomainError, match="Missing hourly"):
        grid(timegap=7200)


def test_geopotential_conversion_round_trip():
    for z in (-100, 0, 12500, 20000):
        assert geometric_m(geopotential_m(z)) == pytest.approx(z, abs=1e-8)
    assert 12475 < geopotential_m(12500) < 12500


def test_time_step_convergence_in_sheared_wind():
    class Sheared(SyntheticField):
        def get_state(self, lat, lon, altitude_m, time):
            from dataclasses import replace

            state = super().get_state(lat, lon, altitude_m, time)
            return replace(
                state, u_ms=100 + 10 * np.sin(np.radians(lon * 8)), v_ms=20 * np.cos(np.radians(lat * 5))
            )

    results = []
    for step in (120, 60, 5):
        c = mission(integration_step_s=step)
        c.launch.latitude_deg = 60
        results.append(simulate(c, Sheared())["samples"][-1])

    def distance(a, b):
        return Geodesic.WGS84.Inverse(
            a["latitude_deg"], a["longitude_deg"], b["latitude_deg"], b["longitude_deg"]
        )["s12"]

    assert distance(results[0], results[2]) < 0.02
    assert distance(results[1], results[2]) <= distance(results[0], results[2]) + 1e-6
