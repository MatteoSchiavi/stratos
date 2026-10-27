"""Bounded weather interpolation; missing weather is an error, never extrapolated."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import numpy as np
from scipy.interpolate import RegularGridInterpolator

REFERENCE_RADIUS_M = 6_356_766.0


def geopotential_m(geometric_m: float) -> float:
    return REFERENCE_RADIUS_M * geometric_m / (REFERENCE_RADIUS_M + geometric_m)


def geometric_m(height_m: float) -> float:
    return REFERENCE_RADIUS_M * height_m / (REFERENCE_RADIUS_M - height_m)


class WeatherDomainError(ValueError):
    pass


class WeatherSpatialError(WeatherDomainError):
    pass


class WeatherTimeError(WeatherDomainError):
    pass


@dataclass(frozen=True)
class WeatherState:
    u_ms: float
    v_ms: float
    temperature_k: float
    pressure_pa: float
    geopotential_m: float
    valid_before_utc: str
    valid_after_utc: str
    temporal_weight: float
    dataset_id: str | None = None


class WeatherField(Protocol):
    provenance: dict

    def get_state(self, lat: float, lon: float, altitude_m: float, time: datetime) -> WeatherState: ...


class SyntheticField:
    def __init__(self, u_ms: float = 12, v_ms: float = 3):
        self.u_ms, self.v_ms = u_ms, v_ms
        self.provenance: dict = {
            "provider": "SYNTHETIC",
            "origin": "demo",
            "quality": "hypothetical",
            "fixture": "constant-wind-v1",
            "u_ms": u_ms,
            "v_ms": v_ms,
            "source": "generated analytic field, not meteorological observations",
            "temperature_model": "ISA troposphere/isothermal approximation; demonstration only",
        }

    def get_state(self, lat: float, lon: float, altitude_m: float, time: datetime) -> WeatherState:
        if abs(lat) > 89.5:
            raise WeatherDomainError("Polar wind basis beyond 89.5 degrees is unsupported")
        h = geopotential_m(altitude_m)
        t = 288.15 - 0.0065 * min(h, 11000)
        p11 = 101325 * (216.65 / 288.15) ** 5.25588
        p = 101325 * (t / 288.15) ** 5.25588 if h <= 11000 else p11 * np.exp(-(h - 11000) / 6341.62)
        return WeatherState(self.u_ms, self.v_ms, t, float(p), h, time.isoformat(), time.isoformat(), 0)


class GridField:
    """Arrays [time, level, latitude, longitude], GFS HGT in geopotential m.

    Horizontal/time trilinear interpolation first, then interpolation on the actual
    height column. No claim of log-pressure interpolation for winds: pressure is
    recovered logarithmically between bounding height surfaces.
    """

    def __init__(
        self,
        times,
        latitudes,
        longitudes,
        pressures_pa,
        u,
        v,
        temperature,
        height,
        provenance: dict,
        surface: dict | None = None,
        legacy_surface_boundary: bool = False,
    ):
        self.times = np.asarray(times, dtype=float)
        self.lats = np.asarray(latitudes, dtype=float)
        raw_lons = np.asarray(longitudes, dtype=float)
        # Preserve regional continuity across 180 degrees. Global files include periodic seam.
        self.lons = np.rad2deg(np.unwrap(np.deg2rad(raw_lons)))
        self.pressures = np.asarray(pressures_pa, dtype=float)
        if len(self.times) < 2 or len(self.lats) < 2 or len(self.lons) < 2:
            raise WeatherDomainError("Weather grid needs >=2 times, latitudes and longitudes")
        for axis in (self.times, self.lats, self.lons):
            if not np.all(np.isfinite(axis)) or not np.all(np.diff(axis) > 0):
                raise WeatherDomainError("Grid coordinates must be strictly increasing")
        if len(self.pressures) < 2 or not np.all(np.isfinite(self.pressures)) or np.any(self.pressures <= 0):
            raise WeatherDomainError("At least two finite positive pressure levels are required")
        if len(np.unique(self.pressures)) != len(self.pressures):
            raise WeatherDomainError("Duplicate pressure levels")
        if np.any(np.diff(self.times) > 3600.1):
            raise WeatherDomainError("Missing hourly forecast lead; temporal bridging is forbidden")
        self.provenance = provenance
        self.legacy_surface_boundary = legacy_surface_boundary
        self.interpolators = []
        for arr in (u, v, temperature, height):
            values = np.moveaxis(np.asarray(arr, dtype=float), 1, -1)
            if values.shape != (len(self.times), len(self.lats), len(self.lons), len(self.pressures)):
                raise WeatherDomainError("Weather field shape mismatch")
            self.interpolators.append(
                RegularGridInterpolator((self.times, self.lats, self.lons), values, bounds_error=True)
            )
        self.surface = {
            k: RegularGridInterpolator((self.times, self.lats, self.lons), values, bounds_error=True)
            for k, values in (surface or {}).items()
        }
        if self.surface and set(self.surface) != {"height", "pressure", "u", "v", "temperature"}:
            raise WeatherDomainError("Surface boundary requires height, pressure, U/V and temperature")
        self.combined: RegularGridInterpolator | None = None
        self.surface_names = list(self.surface)
        if not legacy_surface_boundary:
            # One vector-valued interpolation, rather than nine identical searches
            # and weight calculations per integration stage. Legacy arithmetic is
            # retained separately so historical output hashes remain reproducible.
            channels = [f.values for f in self.interpolators]
            channels.extend(f.values[..., None] for f in self.surface.values())
            self.combined = RegularGridInterpolator(
                (self.times, self.lats, self.lons), np.concatenate(channels, axis=-1), bounds_error=True
            )
            self.interpolators.clear()
            self.surface.clear()

    def point(self, lat: float, lon: float, time: datetime) -> list[list[float]]:
        if time.tzinfo is None or not all(np.isfinite([lat, lon])):
            raise WeatherDomainError("Finite coordinates and an explicitly zoned UTC timestamp are required")
        stamp = time.timestamp()
        if stamp < self.times[0] or stamp > self.times[-1]:
            raise WeatherTimeError("Outside forecast valid-time horizon; no temporal extrapolation")
        lon += 360 * round((float(np.mean(self.lons)) - lon) / 360)
        if not self.lats[0] <= lat <= self.lats[-1] or not self.lons[0] <= lon <= self.lons[-1]:
            raise WeatherSpatialError("Outside downloaded geographic ROI; no spatial extrapolation")
        return [[stamp, lat, lon]]

    def column(self, lat: float, lon: float, time: datetime) -> tuple[list[np.ndarray], dict]:
        point = self.point(lat, lon, time)
        if self.combined is not None:
            values = self.combined(point)[0]
            count = len(self.pressures)
            return (
                [values[i * count : (i + 1) * count] for i in range(4)],
                {name: float(values[4 * count + i]) for i, name in enumerate(self.surface_names)},
            )
        return (
            [f(point)[0] for f in self.interpolators],
            {k: float(f(point)[0]) for k, f in self.surface.items()},
        )

    def get_isobaric_state(self, lat: float, lon: float, pressure_pa: float, time: datetime) -> WeatherState:
        """Sample one actual pressure surface; its height varies with space/time.

        No standard-atmosphere conversion or vertical pressure extrapolation is
        used. Surface pressure and height mask physically underground levels.
        """
        if abs(lat) > 89.5 or not np.isfinite(pressure_pa):
            raise WeatherDomainError(
                "Finite pressure and coordinates within the supported polar basis required"
            )
        matches = np.flatnonzero(np.isclose(self.pressures, pressure_pa, rtol=0, atol=0.01))
        if len(matches) != 1:
            raise WeatherDomainError("Requested pressure is not an available retained GFS isobaric level")
        (u, v, temperature, height), surface = self.column(lat, lon, time)
        i = int(matches[0])
        values = [u[i], v[i], temperature[i], height[i]]
        if not np.all(np.isfinite(values)) or temperature[i] <= 0:
            raise WeatherDomainError("Missing/NaN or nonphysical isobaric weather cell")
        if surface:
            if not np.all(np.isfinite(list(surface.values()))) or surface["pressure"] <= 0:
                raise WeatherDomainError("Missing or nonphysical surface data")
            if pressure_pa >= surface["pressure"] or height[i] <= surface["height"]:
                raise WeatherDomainError("Selected isobaric surface is at/below GFS coarse model terrain")
        upper = min(
            max(int(np.searchsorted(self.times, time.timestamp(), side="right")), 1), len(self.times) - 1
        )
        low = upper - 1
        return WeatherState(
            float(u[i]),
            float(v[i]),
            float(temperature[i]),
            float(self.pressures[i]),
            float(height[i]),
            datetime.fromtimestamp(self.times[low], UTC).isoformat(),
            datetime.fromtimestamp(self.times[upper], UTC).isoformat(),
            float((time.timestamp() - self.times[low]) / (self.times[upper] - self.times[low])),
            self.provenance.get("id"),
        )

    def get_state(self, lat: float, lon: float, altitude_m: float, time: datetime) -> WeatherState:
        if abs(lat) > 89.5:
            raise WeatherDomainError("Polar wind basis beyond 89.5 degrees is unsupported")
        if not np.isfinite(altitude_m):
            raise WeatherDomainError("Altitude must be finite geometric MSL metres")
        stamp = time.timestamp()
        (u, v, temp, h), surface = self.column(lat, lon, time)
        if surface and not all(np.isfinite(list(surface.values()))):
            raise WeatherDomainError("Missing surface data")
        p = self.pressures.copy()
        if surface:
            terrain = surface["height"]
            if geopotential_m(altitude_m) < terrain - 0.01:
                raise WeatherDomainError(
                    f"Below GFS coarse model terrain ({geometric_m(float(terrain)):.1f} m geometric MSL); check site elevation / initial altitude"
                )
            # Remove physically underground isobaric levels only when surface pressure proves it.
            above = (p < surface["pressure"]) & ((h > terrain + 10) | ~np.isfinite(h))
            if self.legacy_surface_boundary:
                if not np.all(np.isfinite([u, v, temp, h])):
                    raise WeatherDomainError("Missing/NaN weather cell or pressure level")
                above &= h > terrain + 10
            u = np.r_[surface["u"], u[above]]
            v = np.r_[surface["v"], v[above]]
            temp = np.r_[surface["temperature"], temp[above]]
            h = np.r_[terrain, h[above]]
            p = np.r_[surface["pressure"], p[above]]
        # Underground levels may legitimately be missing; pressure proves they
        # are excluded. An above-ground missing level is never bridged.
        if not np.all(np.isfinite([u, v, temp, h, p])):
            raise WeatherDomainError("Missing/NaN weather cell or pressure level")
        if np.any(temp <= 0) or np.any(p <= 0):
            raise WeatherDomainError("Nonphysical temperature or pressure column")
        order = np.argsort(h)
        h, u, v, temp, p = [a[order] for a in (h, u, v, temp, p)]
        if np.any(np.diff(h) <= 0) or np.any(np.diff(p) >= 0):
            raise WeatherDomainError("Nonphysical height/pressure column")
        target = geopotential_m(altitude_m)
        if not h[0] <= target <= h[-1]:
            raise WeatherDomainError(
                "Altitude outside available GFS height column; no vertical extrapolation"
            )
        upper = int(np.searchsorted(self.times, stamp, side="right"))
        upper = min(max(upper, 1), len(self.times) - 1)
        low = upper - 1
        weight = (stamp - self.times[low]) / (self.times[upper] - self.times[low])
        return WeatherState(
            float(np.interp(target, h, u)),
            float(np.interp(target, h, v)),
            float(np.interp(target, h, temp)),
            float(np.exp(np.interp(target, h, np.log(p)))),
            target,
            datetime.fromtimestamp(self.times[low], UTC).isoformat(),
            datetime.fromtimestamp(self.times[upper], UTC).isoformat(),
            float(weight),
            self.provenance.get("id"),
        )
