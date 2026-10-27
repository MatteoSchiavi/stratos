"""Read-only bounded weather slices and physical wind/profile inspection."""

import math
from collections import OrderedDict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

import numpy as np
from geographiclib.geodesic import Geodesic

from packages.domain.models import ExploreRequest, digest
from packages.flight.geojson import geometry
from packages.meteo.contours import contour_lines
from packages.meteo.field import GridField, WeatherDomainError, geometric_m
from packages.meteo.gfs import open_cached


class SliceCache:
    def __init__(self, capacity: int = 2):
        self.capacity = capacity
        self.items: OrderedDict[tuple, GridField] = OrderedDict()
        self.lock = Lock()

    def get(self, directory: Path, when: datetime) -> GridField:
        key = (
            str(directory.resolve()),
            int(when.timestamp() // 3600),
            tuple(
                (p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(directory.glob("*.grib2"))
            ),
            (directory / "manifest.json").stat().st_mtime_ns,
        )
        with self.lock:
            if key not in self.items:
                # Decode only the two bounding leads, never a full 48-hour volume
                # on every cursor move. open_cached verifies their checksums.
                self.items[key] = open_cached(directory, at_time=when)
            self.items.move_to_end(key)
            while len(self.items) > self.capacity:
                self.items.popitem(last=False)
            return self.items[key]


def explore(field: GridField, request: ExploreRequest) -> dict:
    lat, lon, when = request.latitude_deg, request.longitude_deg, request.time_utc

    def sample(y, x):
        if request.plane == "isobaric":
            assert request.pressure_pa is not None
            return field.get_isobaric_state(float(y), float(x), request.pressure_pa, when)
        return field.get_state(float(y), float(x), request.geometric_msl_m, when)

    sampled = sample(lat, lon)
    (u, v, temp, heights), surface = field.column(lat, lon, when)
    profile = []
    for pressure, uu, vv, temperature, h in zip(field.pressures, u, v, temp, heights, strict=True):
        if (
            np.all(np.isfinite([pressure, uu, vv, temperature, h]))
            and temperature > 0
            and (not surface or (pressure < surface["pressure"] and h > surface["height"]))
        ):
            profile.append(
                {
                    "pressure_pa": float(pressure),
                    "geometric_msl_m": geometric_m(float(h)),
                    "geopotential_m": float(h),
                    "u_ms": float(uu),
                    "v_ms": float(vv),
                    "speed_ms": float(math.hypot(uu, vv)),
                    "temperature_k": float(temperature),
                }
            )
    west, east = float(field.lons[0]), float(field.lons[-1])
    south, north = float(field.lats[0]), float(field.lats[-1])
    arrows, tips, unavailable = [], [], 0
    for yy in np.linspace(south, north, request.grid_size):
        for xx in np.linspace(west, east, request.grid_size):
            try:
                wind = sample(yy, xx)
            except WeatherDomainError:
                unavailable += 1
                continue
            end = Geodesic.WGS84.Direct(
                yy, xx, math.degrees(math.atan2(wind.u_ms, wind.v_ms)), math.hypot(wind.u_ms, wind.v_ms) * 600
            )
            arrows.append(
                {
                    "type": "Feature",
                    "properties": {
                        "u_ms": wind.u_ms,
                        "v_ms": wind.v_ms,
                        "speed_ms": math.hypot(wind.u_ms, wind.v_ms),
                    },
                    "geometry": geometry(
                        [
                            {"longitude_deg": (float(xx) + 180) % 360 - 180, "latitude_deg": float(yy)},
                            {"longitude_deg": end["lon2"], "latitude_deg": end["lat2"]},
                        ]
                    ),
                }
            )
            tips.append(
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": [end["lon2"], end["lat2"]]},
                }
            )
    xs = np.linspace(west, east, request.contour_grid_size)
    ys = np.linspace(south, north, request.contour_grid_size)
    values = np.full((len(ys), len(xs)), np.nan)
    for i, yy in enumerate(ys):
        for j, xx in enumerate(xs):
            try:
                state = sample(yy, xx)
                values[i, j] = (
                    math.hypot(state.u_ms, state.v_ms)
                    if request.contour_variable == "wind_speed"
                    else state.temperature_k
                )
            except WeatherDomainError:
                continue
    lines = contour_lines(xs, ys, values)
    finite = values[np.isfinite(values)]
    scalar = {
        "variable": request.contour_variable,
        "units": "m/s" if request.contour_variable == "wind_speed" else "K",
        "minimum": float(finite.min()) if len(finite) else None,
        "maximum": float(finite.max()) if len(finite) else None,
        "longitudes_deg": xs.tolist(),
        "latitudes_deg": ys.tolist(),
        "values": [[float(v) if np.isfinite(v) else None for v in row] for row in values],
        "grid_size": request.contour_grid_size,
        "invalid_nodes": int(values.size - len(finite)),
        "native_grid_deg": field.provenance.get("grid_deg"),
        "status": "unavailable" if not len(finite) else "flat" if not lines["levels"] else "available",
        "levels": lines["levels"],
        "masked_cells": lines["masked_cells"],
        "valid_cells": lines["valid_cells"],
        "algorithm": lines["algorithm"],
        "interpretation": "Display contours interpolate sampled forecast values; they add no model resolution or observations.",
    }
    result = {
        "schema_version": 2,
        "request": request.model_dump(mode="json"),
        "plane": {
            "kind": request.plane,
            "pressure_pa": request.pressure_pa,
            "geometric_msl_m": request.geometric_msl_m if request.plane == "geometric_altitude" else None,
        },
        "point": {
            "latitude_deg": lat,
            "longitude_deg": lon,
            "geometric_msl_m": geometric_m(sampled.geopotential_m)
            if request.plane == "isobaric"
            else request.geometric_msl_m,
            "time_utc": when.astimezone(UTC).isoformat(),
            **asdict(sampled),
        },
        "profile": sorted(profile, key=lambda p: p["geometric_msl_m"]),
        "available_pressure_levels_pa": sorted(field.pressures.tolist(), reverse=True),
        "wind_vectors": {"type": "FeatureCollection", "features": arrows},
        "wind_tips": {"type": "FeatureCollection", "features": tips},
        "contours": lines["geojson"],
        "scalar_field": scalar,
        "unavailable_cells": unavailable,
        "bounds": [west, south, east, north],
        "provenance": field.provenance,
        "quality": "forecast_not_observation",
        "vector_scale_seconds": 600,
        "limitations": [
            "Coarse GFS forecast, not observed weather.",
            "Invalid samples/cells are masked, never bridged by contours or extrapolation.",
            "Isobaric views use actual retained pressure surfaces and their variable model heights.",
            "Surface wind/temperature are 10m/2m product boundary approximations.",
            scalar["interpretation"],
        ],
    }
    return {**result, "inspection_sha256": digest(result)}
