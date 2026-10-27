import math

import pytest
from geographiclib.geodesic import Geodesic
from scipy.optimize import brentq

from packages.domain.models import MissionConfig
from packages.flight.integrator import simulate
from packages.meteo.field import SyntheticField


def config(lat=0, lon=0, altitude=12500, sample=120):
    c = MissionConfig()
    c.launch.latitude_deg, c.launch.longitude_deg = lat, lon
    c.flight.initial_geometric_m = c.flight.target_geometric_m = altitude
    c.flight.float_duration_hours = 1
    c.flight.sample_interval_s = sample
    return c


def test_altitude_aware_equatorial_exact_angular_displacement():
    c = config()
    output = simulate(c, SyntheticField(20, 0))
    radius = Geodesic.WGS84.a
    expected_lon = math.degrees(72000 / (radius + 12500))
    assert output["samples"][-1]["longitude_deg"] == pytest.approx(expected_lon, abs=1e-10)
    assert output["horizontal_air_distance_m"] == pytest.approx(72000, abs=1e-7)
    assert output["distance_m"] == pytest.approx(72000 * radius / (radius + 12500), abs=1e-6)
    assert output["solver_version"] == "wgs84-height-rk4-v2"


def test_altitude_aware_meridional_displacement_against_independent_geodesic_arc():
    c = config(lat=65)
    output = simulate(c, SyntheticField(0, 35))
    first = math.radians(65)

    def arc(phi):
        # Independent library surface arc plus the analytic height correction;
        # do not reuse the curvature function being tested as its own oracle.
        surface = Geodesic.WGS84.Inverse(65, 0, math.degrees(phi), 0)["s12"]
        return surface + 12500 * (phi - first)

    expected = math.degrees(brentq(lambda phi: arc(phi) - 35 * 3600, first, first + 0.1, xtol=1e-14))
    assert output["samples"][-1]["latitude_deg"] == pytest.approx(expected, abs=1e-9)


def test_snapshot_cadence_does_not_change_path_or_integrated_distance():
    class Turning(SyntheticField):
        def get_state(self, lat, lon, z, time):
            from dataclasses import replace

            state = super().get_state(lat, lon, z, time)
            return replace(
                state, u_ms=30 * math.cos(time.timestamp() / 150), v_ms=30 * math.sin(time.timestamp() / 150)
            )

    outputs = [simulate(config(sample=s), Turning()) for s in (37, 120, 300)]
    for output in outputs[1:]:
        for key in ("latitude_deg", "longitude_deg", "distance_m", "horizontal_air_distance_m"):
            assert output["samples"][-1][key] == outputs[0]["samples"][-1][key]
    assert len(outputs[0]["samples"]) > len(outputs[-1]["samples"])


def test_legacy_solver_is_explicit_and_preserved():
    c = config()
    c.schema_version = 1
    output = simulate(c, SyntheticField(20, 0))
    assert "solver_version" not in output
    assert output["distance_m"] == pytest.approx(72000, abs=0.02)
