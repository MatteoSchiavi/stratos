from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from scipy.interpolate import RegularGridInterpolator

from packages.domain.models import ExploreRequest, digest
from packages.meteo.contours import contour_lines, nice_levels
from packages.meteo.explorer import explore
from packages.meteo.field import GridField, WeatherDomainError, geometric_m

START = datetime(2026, 10, 27, 12, tzinfo=UTC)


def pressure_field(*, surface=True, longitude=(8, 9, 10), missing_level=None):
    tt, level, yy, xx = np.meshgrid([0, 1], [0, 1, 2], [0, 1, 2], [0, 1, 2], indexing="ij")
    h = np.array([250, 5500, 12000])[level] + xx * 100 + yy * 50 + tt * 20
    u = (level * 10 + xx * 2 + yy + tt * 4).astype(float)
    if missing_level is not None:
        u[:, missing_level] = np.nan
    ts, ys, xs = np.meshgrid([0, 1], [0, 1, 2], [0, 1, 2], indexing="ij")
    boundary = {
        "height": 100 + xs * 1000,
        "pressure": 101000 - xs * 8000,
        "temperature": np.full(xs.shape, 280),
        "u": np.ones(xs.shape),
        "v": np.zeros(xs.shape),
    }
    return GridField(
        [START.timestamp(), START.timestamp() + 3600],
        [40, 41, 42],
        longitude,
        [100000, 50000, 20000],
        u,
        np.full(u.shape, -2),
        250 + h / 1000,
        h,
        {"id": "analytic", "provider": "NOAA_GFS", "grid_deg": 0.25},
        surface=boundary if surface else None,
    )


def test_pressure_surface_uses_actual_height_and_horizontal_time_interpolation():
    field = pressure_field()
    state = field.get_isobaric_state(40.5, 8.5, 50000, START + timedelta(minutes=30))
    assert state.u_ms == pytest.approx(10 + 1 + 0.5 + 2)
    assert state.pressure_pa == 50000
    assert state.geopotential_m == pytest.approx(5500 + 50 + 25 + 10)
    assert state.temperature_k == pytest.approx(250 + state.geopotential_m / 1000)
    assert state.temporal_weight == 0.5
    # Its geometric altitude varies; it is not a fixed standard-atmosphere level.
    other = field.get_isobaric_state(40.5, 9.5, 50000, START + timedelta(minutes=30))
    assert geometric_m(other.geopotential_m) > geometric_m(state.geopotential_m) + 99


def test_pressure_plane_masks_terrain_and_never_invents_unretained_levels():
    field = pressure_field()
    with pytest.raises(WeatherDomainError, match="terrain"):
        field.get_isobaric_state(41, 9.5, 100000, START)
    with pytest.raises(WeatherDomainError, match="available retained"):
        field.get_isobaric_state(41, 8.5, 40000, START)
    with pytest.raises(WeatherDomainError, match="horizon"):
        field.get_isobaric_state(41, 8.5, 50000, START - timedelta(seconds=1))
    with pytest.raises(WeatherDomainError, match="UTC"):
        field.get_isobaric_state(41, 8.5, 50000, START.replace(tzinfo=None))
    field = pressure_field(missing_level=2)
    assert field.get_isobaric_state(41, 8.5, 50000, START).pressure_pa == 50000
    with pytest.raises(WeatherDomainError, match="Missing/NaN"):
        field.get_isobaric_state(41, 8.5, 20000, START)


def paths(result):
    for feature in result["geojson"]["features"]:
        g = feature["geometry"]
        for line in [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]:
            yield feature["properties"]["value"], line


def test_linear_contours_match_independent_interpolation_and_join_cells():
    x, y = np.linspace(0, 4, 9), np.linspace(0, 3, 7)
    xx, yy = np.meshgrid(x, y)
    z = xx + 2 * yy
    result = contour_lines(x, y, z, levels=[1.3, 3.5, 5])
    reference = RegularGridInterpolator((y, x), z)
    assert len(result["geojson"]["features"]) == 3
    assert result["masked_cells"] == 0
    for level, line in paths(result):
        for px, py in line:
            assert px + 2 * py == pytest.approx(level, abs=1e-12)
            assert reference([[py, px]])[0] == pytest.approx(level, abs=1e-12)


@pytest.mark.parametrize(
    "z,expected",
    [
        ([[2, -1], [-1, 2]], [((2 / 3, 0), (1, 1 / 3)), ((0, 2 / 3), (1 / 3, 1))]),
        ([[1, -2], [-2, 1]], [((1 / 3, 0), (0, 1 / 3)), ((1, 2 / 3), (2 / 3, 1))]),
    ],
)
def test_asymptotic_saddle_decision_has_correct_connectivity(z, expected):
    result = contour_lines([0, 1], [0, 1], z, [0])
    lines = [np.array(line) for _, line in paths(result)]
    assert len(lines) == 2
    for ends in expected:
        assert any(np.allclose(line, ends) or np.allclose(line[::-1], ends) for line in lines)


def test_exact_saddle_retains_four_branches_at_critical_point():
    result = contour_lines([0, 1], [0, 1], [[1, -1], [-1, 1]], [0])
    lines = list(paths(result))
    assert len(lines) == 4
    for _, line in lines:
        assert [0.5, 0.5] in line


def test_missing_cells_break_contours_and_closed_loops_remain_closed():
    x = np.arange(5)
    z = np.broadcast_to(x, (5, 5)).astype(float).copy()
    z[2, 2] = np.nan
    result = contour_lines(x, x, z, [1.5])
    assert result["masked_cells"] == 4
    lines = [line for _, line in paths(result)]
    assert len(lines) == 2
    for line in lines:
        assert all(p[1] <= 1 for p in line) or all(p[1] >= 3 for p in line)
    xx, yy = np.meshgrid(x - 2, x - 2)
    loop = list(paths(contour_lines(x - 2, x - 2, xx**2 + yy**2, [1.5])))
    assert len(loop) == 1
    assert loop[0][1][0] == loop[0][1][-1]


def test_contour_dateline_flat_masked_and_resource_contracts():
    result = contour_lines([179, 180, 181], [0, 1], [[0, 0, 0], [1, 1, 1]], [0.5])
    assert result["geojson"]["features"][0]["geometry"]["type"] == "MultiLineString"
    for _, line in paths(result):
        assert all(-180 <= point[0] <= 180 for point in line)
        assert all(abs(a[0] - b[0]) <= 180 for a, b in zip(line, line[1:], strict=False))
    assert nice_levels(np.ones((2, 2))) == []
    assert contour_lines([0, 1], [0, 1], np.full((2, 2), np.nan))["valid_cells"] == 0
    with pytest.raises(ValueError):
        contour_lines([0, 0], [0, 1], np.ones((2, 2)))
    with pytest.raises(ValueError):
        contour_lines([0, 1], [0, 1], np.ones((2, 2)), list(range(13)))


def test_plane_request_validation_and_inspection_hash_and_masks():
    from pydantic import ValidationError

    base = dict(dataset_id="analytic", time_utc=START, latitude_deg=40.5, longitude_deg=8.1)
    with pytest.raises(ValidationError, match="explicit retained pressure"):
        ExploreRequest(**base, plane="isobaric")
    with pytest.raises(ValidationError, match="omitted"):
        ExploreRequest(**base, pressure_pa=50000)
    request = ExploreRequest(**base, plane="isobaric", pressure_pa=100000, contour_grid_size=17)
    result = explore(pressure_field(), request)
    assert result["point"]["pressure_pa"] == 100000
    assert result["plane"]["geometric_msl_m"] is None
    assert result["scalar_field"]["invalid_nodes"] > 0
    assert result["scalar_field"]["masked_cells"] > 0
    assert any(v is None for row in result["scalar_field"]["values"] for v in row)
    assert (
        digest({k: v for k, v in result.items() if k != "inspection_sha256"}) == result["inspection_sha256"]
    )


def test_pressure_inspection_wind_glyphs_do_not_span_world_at_dateline():
    result = explore(
        pressure_field(surface=False, longitude=(179.75, 180, 180.25)),
        ExploreRequest(
            dataset_id="analytic",
            time_utc=START,
            latitude_deg=41,
            longitude_deg=179.9,
            plane="isobaric",
            pressure_pa=20000,
            contour_grid_size=17,
        ),
    )
    assert any(f["geometry"]["type"] == "MultiLineString" for f in result["wind_vectors"]["features"])
    for feature in result["wind_vectors"]["features"]:
        g = feature["geometry"]
        for line in [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]:
            assert all(abs(a[0] - b[0]) <= 180 for a, b in zip(line, line[1:], strict=False))
    assert len(result["wind_tips"]["features"]) == len(result["wind_vectors"]["features"])


def test_real_isobaric_api_matches_direct_eccodes_and_rejects_identity_drift(tmp_path, monkeypatch):
    import json
    import shutil
    from pathlib import Path

    import eccodes as ec
    from fastapi.testclient import TestClient

    from services.api.main import create_app
    from services.api.storage import Record

    source = Path(__file__).parent / "fixtures/noaa-gfs-20261027-06"
    metadata = json.loads((source / "manifest.json").read_text())
    shutil.copytree(source, tmp_path / "cache" / metadata["id"])
    direct = {}
    with (source / "f006.grib2").open("rb") as stream:
        while (handle := ec.codes_grib_new_from_file(stream)) is not None:
            try:
                if (
                    ec.codes_get(handle, "typeOfLevel") == "isobaricInhPa"
                    and ec.codes_get(handle, "level") == 200
                ):
                    name = ec.codes_get(handle, "shortName")
                    if name in ("u", "v", "t", "gh"):
                        direct[name] = ec.codes_grib_find_nearest(handle, 45, 9.75)[0]["value"]
            finally:
                ec.codes_release(handle)
    app = create_app(tmp_path, seed=False)
    body = dict(
        dataset_id=metadata["id"],
        time_utc=START.isoformat(),
        latitude_deg=45,
        longitude_deg=9.75,
        plane="isobaric",
        pressure_pa=20000,
        contour_variable="temperature",
        contour_grid_size=17,
    )
    with TestClient(app) as client:
        with app.state.sessions() as session:
            session.add(Record(id=metadata["id"], kind="dataset", payload=metadata))
            session.commit()
        response = client.post("/api/weather/explore", json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        for key, name in [("u_ms", "u"), ("v_ms", "v"), ("temperature_k", "t"), ("geopotential_m", "gh")]:
            assert result["point"][key] == pytest.approx(direct[name], abs=1e-8)
        assert result["point"]["geometric_msl_m"] == pytest.approx(geometric_m(direct["gh"]), abs=1e-8)
        assert result["scalar_field"]["units"] == "K"
        assert result["scalar_field"]["native_grid_deg"] == 0.25
        assert len(result["contours"]["features"]) > 0
        assert (
            digest({k: v for k, v in result.items() if k != "inspection_sha256"})
            == result["inspection_sha256"]
        )
        unavailable = client.post("/api/weather/explore", json={**body, "pressure_pa": 33333})
        assert unavailable.status_code == 422
        with app.state.sessions() as session:
            record = session.get(Record, metadata["id"])
            record.payload = {**metadata, "sha256": "changed"}
            session.commit()
        drift = client.post("/api/weather/explore", json=body)
        assert drift.status_code == 422
        assert "identity differs" in drift.json()["detail"]
        with app.state.sessions() as session:
            record = session.get(Record, metadata["id"])
            record.payload = metadata
            session.commit()
        from services.api import main as api_module

        monkeypatch.setattr(
            api_module,
            "API_RUNTIME_CODE",
            {**api_module.API_RUNTIME_CODE, "scientific_source_sha256": "stale"},
        )
        stale = client.post("/api/weather/explore", json=body)
        assert stale.status_code == 422
        assert "restart the API/worker" in stale.json()["detail"]


def test_contour_levels_keep_small_finite_ranges_and_reject_overflow():
    levels = nice_levels(np.array([[0, 2e-12], [0, 2e-12]]))
    assert len(levels) > 0
    assert all(0 < v < 2e-12 for v in levels)
    assert all(b > a for a, b in zip(levels, levels[1:], strict=False))
    with pytest.raises(ValueError, match="finite contour arithmetic"):
        nice_levels(np.array([[-1e308, 1e308]]))
