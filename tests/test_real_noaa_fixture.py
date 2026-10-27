"""Actual NOAA GFS crop downloaded 2026-10-27; tests require no network."""

from datetime import UTC, datetime
from pathlib import Path

import eccodes as ec
import pytest
import xarray as xr

from packages.meteo.field import geometric_m
from packages.meteo.gfs import open_cached

DIRECTORY = Path(__file__).parent / "fixtures/noaa-gfs-20261027-06"


def test_actual_noaa_fixture_against_independent_point_and_cfgrib():
    grid = open_cached(DIRECTORY)
    point = {}
    path = DIRECTORY / "f006.grib2"
    with path.open("rb") as stream:
        while (h := ec.codes_grib_new_from_file(stream)) is not None:
            try:
                if ec.codes_get(h, "typeOfLevel") == "isobaricInhPa" and ec.codes_get(h, "level") == 200:
                    name = ec.codes_get(h, "shortName")
                    if name in ("u", "v", "t", "gh"):
                        point[name] = ec.codes_grib_find_nearest(h, 45, 9.75)[0]["value"]
            finally:
                ec.codes_release(h)
    state = grid.get_state(45, 9.75, geometric_m(point["gh"]), datetime(2026, 10, 27, 12, tzinfo=UTC))
    assert state.u_ms == pytest.approx(point["u"], abs=1e-8)
    assert state.v_ms == pytest.approx(point["v"], abs=1e-8)
    assert state.temperature_k == pytest.approx(point["t"], abs=1e-8)
    assert state.pressure_pa == pytest.approx(20000, abs=1e-6)
    with xr.open_dataset(
        path,
        engine="cfgrib",
        backend_kwargs={"filter_by_keys": {"typeOfLevel": "isobaricInhPa"}, "indexpath": ""},
    ) as ds:
        independent = ds.sel(isobaricInhPa=200, latitude=45, longitude=9.75)
        assert float(independent.u) == pytest.approx(state.u_ms, abs=1e-5)
        assert float(independent.v) == pytest.approx(state.v_ms, abs=1e-5)
    assert grid.provenance["origin"] == "forecast"
    assert grid.provenance["run_utc"] == "2026-10-27T06:00:00+00:00"


def test_actual_noaa_time_interpolation_is_bounded_and_not_constant():
    grid = open_cached(DIRECTORY)
    start = grid.get_state(45, 9.75, 12500, datetime(2026, 10, 27, 12, tzinfo=UTC))
    middle = grid.get_state(45, 9.75, 12500, datetime(2026, 10, 27, 12, 30, tzinfo=UTC))
    end = grid.get_state(45, 9.75, 12500, datetime(2026, 10, 27, 13, tzinfo=UTC))
    assert middle.temporal_weight == 0.5
    assert min(start.u_ms, end.u_ms) - 0.1 <= middle.u_ms <= max(start.u_ms, end.u_ms) + 0.1
    assert start.u_ms != end.u_ms


@pytest.mark.parametrize("name", ["noaa-simulation.json", "noaa-ascent-simulation.json"])
def test_reproduce_actual_noaa_predictions_offline(name):
    from scripts.reproduce import reproduce
    from services.api.storage import ROOT

    result = reproduce(ROOT / "docs/examples" / name)
    assert result["provider"] == "NOAA_GFS"
    assert result["samples"] > 10
