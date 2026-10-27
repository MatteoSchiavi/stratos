"""Bounded, pinned-run weather windows with optional adjacent-crop acquisition."""

import math
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from packages.domain.models import Cancelled, DownloadRequest, ExpansionPolicy
from packages.meteo.field import GridField, WeatherDomainError, WeatherSpatialError, WeatherTimeError
from packages.meteo.gfs import fetch_subset, open_cached


class AdaptiveField:
    def __init__(
        self,
        initial: GridField,
        cache: Path,
        policy: ExpansionPolicy | None,
        progress: Callable = lambda *_: None,
        cancelled: Callable = lambda: False,
        fetcher: Callable = fetch_subset,
        loader: Callable = open_cached,
    ):
        self.cache, self.policy, self.progress, self.cancelled = cache, policy, progress, cancelled
        self.fetcher, self.loader = fetcher, loader
        self.request = DownloadRequest.model_validate(initial.provenance["request"])
        self.sources = {initial.provenance["id"]: initial.provenance}
        self.source_requests = {initial.provenance["id"]: self.request}
        self.active: OrderedDict[tuple, GridField] = OrderedDict()
        self.active[(initial.provenance["id"], int(initial.times[0]))] = initial
        self.provenance = dict(initial.provenance)
        self.provenance.update(
            access_mode="bounded_time_windows",
            automatic_roi_expansion=policy is not None,
            expansion_policy=policy.model_dump() if policy else None,
            segments=[initial.provenance],
            overlap_checks=[],
            byte_accounting="sum of verified source bytes, including reused cache files",
        )
        self._account()

    def _account(self):
        self.provenance["verified_source_bytes"] = sum(
            f["size_bytes"] for s in self.sources.values() for f in s["files"]
        )
        self.provenance["segment_count"] = len(self.sources)
        if self.policy and self.provenance["verified_source_bytes"] > self.policy.max_download_mib * 1048576:
            raise WeatherDomainError(
                "Initial weather source exceeds the explicit expansion input-byte budget"
            )

    def _keep(self, field: GridField):
        key = (field.provenance["id"], int(field.times[0]))
        self.active[key] = field
        self.active.move_to_end(key)
        while len(self.active) > 3:
            self.active.popitem(last=False)

    @staticmethod
    def _covers(r, lat, lon, when):
        lead = (when - r.run_utc).total_seconds() / 3600
        lon += 360 * round(((r.west_deg + r.east_deg) / 2 - lon) / 360)
        return (
            r.first_lead_hour <= lead <= r.last_lead_hour
            and r.south_deg <= lat <= r.north_deg
            and r.west_deg <= lon <= r.east_deg
        )

    def get_state(self, lat, lon, altitude_m, when):
        lead = (when - self.request.run_utc).total_seconds() / 3600
        if not self.request.first_lead_hour <= lead <= self.request.last_lead_hour:
            raise WeatherTimeError(
                "Outside selected forecast valid-time horizon; ROI expansion cannot extend time"
            )
        if abs(lat) > 89.5:
            raise WeatherDomainError("Polar wind basis beyond 89.5 degrees is unsupported")
        # Source precedence is stable and independent of the decoded LRU order.
        # Inspecting an earlier sample must not change which overlapping crop is used.
        for ident in self.sources:
            if self._covers(self.source_requests[ident], lat, lon, when):
                for key, field in reversed(list(self.active.items())):
                    if key[0] != ident:
                        continue
                    try:
                        value = field.get_state(lat, lon, altitude_m, when)
                        self.active.move_to_end(key)
                        return value
                    except (WeatherSpatialError, WeatherTimeError):
                        pass
                candidate = self.loader(self.cache / ident, at_time=when)
                try:
                    value = candidate.get_state(lat, lon, altitude_m, when)
                except WeatherSpatialError:
                    continue
                self._keep(candidate)
                return value
        if self.policy is None:
            raise WeatherSpatialError("Outside downloaded geographic ROI; automatic expansion is disabled")
        if self.cancelled():
            raise Cancelled("Cancelled before adjacent weather fetch")
        if len(self.sources) >= self.policy.max_tiles:
            raise WeatherDomainError("Explicit weather segment quota exhausted; no extrapolation")
        center_lon = 6 * math.floor((lon + 3) / 6)
        center_lon = (center_lon + 180) % 360 - 180
        center_lat = max(-85, min(85, 6 * math.floor((lat + 3) / 6)))
        first = max(self.request.first_lead_hour, min(math.floor(lead) - 1, self.request.last_lead_hour - 1))
        last = min(self.request.last_lead_hour, first + 4)
        request = DownloadRequest(
            run_utc=self.request.run_utc,
            first_lead_hour=first,
            last_lead_hour=last,
            west_deg=max(-180, center_lon - 4),
            east_deg=min(180, center_lon + 4),
            south_deg=max(-89.5, center_lat - 4),
            north_deg=min(89.5, center_lat + 4),
        )
        remaining = self.policy.max_download_mib * 1048576 - self.provenance["verified_source_bytes"]
        manifest = self.fetcher(
            request, self.cache, self.progress, self.cancelled, budget_limit_bytes=remaining
        )
        for name in ("run_utc", "provider", "member", "grid_deg"):
            if manifest[name] != self.provenance[name]:
                raise WeatherDomainError("Adjacent crop changes the pinned forecast identity")
        if manifest["id"] in self.sources:
            raise WeatherDomainError("Cached adjacent crop does not cover the requested state")
        candidate = self.loader(self.cache / manifest["id"], at_time=when)
        overlap = self._validate_overlap(candidate)
        self.sources[manifest["id"]] = manifest
        self.source_requests[manifest["id"]] = request
        self.provenance["segments"].append(manifest)
        self.provenance["overlap_checks"].append(overlap)
        self._account()
        self._keep(candidate)
        return candidate.get_state(lat, lon, altitude_m, when)

    def _validate_overlap(self, new):
        for old in reversed(list(self.active.values())):
            shift = 360 * round((float(np.mean(old.lons)) - float(np.mean(new.lons))) / 360)
            west, east = max(old.lons[0], new.lons[0] + shift), min(old.lons[-1], new.lons[-1] + shift)
            south, north = max(old.lats[0], new.lats[0]), min(old.lats[-1], new.lats[-1])
            first, last = max(old.times[0], new.times[0]), min(old.times[-1], new.times[-1])
            if west > east or south > north or first > last:
                continue
            from datetime import UTC

            when = datetime.fromtimestamp(float(first), UTC)
            points = [(float(south), float(west)), (float(north), float(east))]
            names = ("u_ms", "v_ms", "temperature_k", "geopotential_m")
            surface_names = {
                "u": "surface_u_ms",
                "v": "surface_v_ms",
                "temperature": "surface_temperature_k",
                "pressure": "surface_pressure_pa",
                "height": "surface_geopotential_m",
            }
            tolerances = {
                "u_ms": 0.01,
                "v_ms": 0.01,
                "temperature_k": 0.01,
                "geopotential_m": 0.05,
                "surface_u_ms": 0.01,
                "surface_v_ms": 0.01,
                "surface_temperature_k": 0.01,
                "surface_pressure_pa": 0.25,
                "surface_geopotential_m": 0.05,
            }
            errors = {name: 0.0 for name in tolerances}
            for lat, lon in points:
                a, sa = old.column(lat, lon, when)
                b, sb = new.column(lat, lon, when)
                for name, aa, bb in zip(names, a, b, strict=True):
                    if not np.allclose(aa, bb, rtol=0, atol=tolerances[name], equal_nan=True):
                        raise WeatherDomainError(
                            "Adjacent weather overlap disagrees; refusing a discontinuous forecast"
                        )
                    if np.any(np.isfinite(aa - bb)):
                        errors[name] = max(errors[name], float(np.nanmax(np.abs(aa - bb))))
                for key in sa:
                    name = surface_names[key]
                    error = abs(sa[key] - sb[key])
                    if error > tolerances[name]:
                        raise WeatherDomainError("Adjacent surface overlap disagrees")
                    errors[name] = max(errors[name], error)
            return {
                "with_dataset_id": old.provenance["id"],
                "at_time_utc": when.isoformat(),
                "points": points,
                "maximum_absolute_errors_by_unit": errors,
                "absolute_tolerances_by_unit": tolerances,
                "tolerance_purpose": "GRIB subset packing consistency, not forecast-skill uncertainty",
                "status": "matched",
            }
        raise WeatherDomainError("No comparable overlapping weather cells; adjacent crop not accepted")
