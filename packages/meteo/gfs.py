"""NOAA NOMADS cropped GRIB2 adapter. No alternate provider or cycle substitution."""

import hashlib
import json
import math
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import httpx
import numpy as np

from packages.domain.models import Cancelled, DownloadRequest, digest, utcnow
from packages.meteo.field import GridField, WeatherDomainError

BASE = "https://nomads.ncep.noaa.gov"
LEVELS_HPA = [
    1000,
    975,
    950,
    925,
    900,
    850,
    800,
    750,
    700,
    650,
    600,
    550,
    500,
    450,
    400,
    350,
    300,
    250,
    200,
    150,
    100,
    70,
    50,
]
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_CACHE_BYTES = 512 * 1024 * 1024
MAX_ARRAY_BYTES = 384 * 1024 * 1024
_next_filter_request_monotonic = 0.0


def wait_for_filter_slot(cancelled: Callable[[], bool]):
    """NOAA's documented ten-second gap, shared by this single-worker process."""
    while True:
        remaining = _next_filter_request_monotonic - time.monotonic()
        if remaining <= 0:
            return
        if cancelled():
            raise Cancelled("Cancelled during NOAA's required ten-second request pacing")
        time.sleep(min(0.1, remaining))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    sync_directory(path.parent)


def sync_directory(path: Path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def estimate_download(request: DownloadRequest) -> dict:
    points = (math.ceil((request.east_deg - request.west_deg) * 4) + 1) * (
        math.ceil((request.north_deg - request.south_deg) * 4) + 1
    )
    files = request.last_lead_hour - request.first_lead_hour + 1
    fields = len(LEVELS_HPA) * 4 + 5
    return {
        "files": files,
        "minimum_filter_wait_seconds": max(0, files - 1) * 10,
        "estimated_bytes": points * fields * files * 2,
        "unpacked_array_bytes": points * fields * files * 8,
        "estimate_kind": "approximate_16bit_packing_plus_variable_GRIB_overhead",
        "cache_limit_bytes": MAX_CACHE_BYTES,
        "memory_limit_bytes": MAX_ARRAY_BYTES,
        "roi": request.model_dump(mode="json"),
        "levels_hpa": LEVELS_HPA,
        "fields": ["UGRD", "VGRD", "TMP", "HGT", "surface PRES", "10m wind", "2m temperature"],
    }


def subset_url(request: DownloadRequest, lead: int) -> str:
    cycle = request.run_utc
    params = {
        "file": f"gfs.t{cycle:%H}z.pgrb2.0p25.f{lead:03d}",
        "dir": f"/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos",
        "subregion": "",
        "leftlon": request.west_deg,
        "rightlon": request.east_deg,
        "toplat": request.north_deg,
        "bottomlat": request.south_deg,
        **{f"var_{v}": "on" for v in ["UGRD", "VGRD", "TMP", "HGT", "PRES"]},
        **{f"lev_{v}_mb": "on" for v in LEVELS_HPA},
        "lev_surface": "on",
        "lev_10_m_above_ground": "on",
        "lev_2_m_above_ground": "on",
    }
    return f"{BASE}/cgi-bin/filter_gfs_0p25.pl?{urlencode(params)}"


def list_available_runs() -> list[dict]:
    """Discover only cycles whose directory and analysis file actually exist."""
    import re

    with httpx.Client(timeout=20, follow_redirects=False, trust_env=True) as client:
        index = client.get(f"{BASE}/pub/data/nccf/com/gfs/prod/")
        index.raise_for_status()
        dates = sorted(set(re.findall(r"gfs\.(\d{8})/", index.text)), reverse=True)[:2]
        result = []
        for day in dates:
            directory = client.get(f"{BASE}/pub/data/nccf/com/gfs/prod/gfs.{day}/")
            directory.raise_for_status()
            cycles = sorted(set(re.findall(r'href="(00|06|12|18)/"', directory.text)), reverse=True)
            for hour in cycles:
                url = f"{BASE}/pub/data/nccf/com/gfs/prod/gfs.{day}/{hour}/atmos/"
                response = client.get(url)
                if response.status_code != 200:
                    continue
                leads = sorted(
                    set(int(v) for v in re.findall(r'pgrb2\.0p25\.f(\d{3})(?:"|<)', response.text))
                )
                if len(leads) < 2:
                    continue
                run = datetime.strptime(day + hour, "%Y%m%d%H").replace(tzinfo=UTC)
                result.append(
                    {
                        "run_utc": run.isoformat(),
                        "provider": "NOAA_GFS",
                        "member": "deterministic",
                        "grid_deg": 0.25,
                        "published_leads_hours": leads,
                        "source_uri": url,
                        "observed_at_utc": utcnow().isoformat(),
                        "publication_time_utc": None,
                        "age_hours": (utcnow() - run).total_seconds() / 3600,
                    }
                )
                if len(result) >= 4:
                    return result
        return result


def fetch_subset(
    request: DownloadRequest,
    cache: Path,
    progress: Callable,
    cancelled: Callable[[], bool] = lambda: False,
    *,
    budget_limit_bytes: int = MAX_CACHE_BYTES,
) -> dict:
    global _next_filter_request_monotonic
    estimate = estimate_download(request)
    if estimate["unpacked_array_bytes"] > MAX_ARRAY_BYTES:
        raise ValueError("Requested decoded grid exceeds 384 MiB limit; reduce ROI or forecast duration")
    if estimate["estimated_bytes"] > MAX_CACHE_BYTES:
        raise ValueError("Estimated download exceeds 512 MiB cache limit")
    dataset_id = "gfs_" + digest(request.model_dump(mode="json"))[:24]
    directory = cache / dataset_id
    directory.mkdir(parents=True, exist_ok=True)
    previous = {}
    if (directory / "manifest.json").exists():
        previous = read_manifest(directory)
    pinned = {f["lead_hour"]: f for f in previous.get("files", [])}
    files: list[dict] = []
    progress(0, "Requesting explicitly selected NOAA cycle")
    with httpx.Client(
        timeout=httpx.Timeout(30, connect=15), follow_redirects=False, trust_env=True
    ) as client:
        for index, lead in enumerate(range(request.first_lead_hour, request.last_lead_hour + 1)):
            if cancelled():
                raise Cancelled("Weather download cancelled; verified completed files retained")
            path = directory / f"f{lead:03d}.grib2"
            metadata_path = directory / f"f{lead:03d}.json"
            url = subset_url(request, lead)
            record = pinned.get(lead)
            if record is None and metadata_path.exists():
                try:
                    record = json.loads(metadata_path.read_text())
                except json.JSONDecodeError:
                    record = None
            if not (path.exists() and record and record.get("sha256") == sha256_file(path)):
                for attempt in range(3):
                    temporary = path.with_suffix(".part")
                    try:
                        wait_for_filter_slot(cancelled)
                        with client.stream("GET", url) as response:
                            response.raise_for_status()
                            total = 0
                            with temporary.open("wb") as stream:
                                for block in response.iter_bytes(64 * 1024):
                                    if cancelled():
                                        raise Cancelled("Weather download cancelled")
                                    total += len(block)
                                    if total + sum(f["size_bytes"] for f in files) > budget_limit_bytes:
                                        raise ValueError("Explicit weather input-byte budget exhausted")
                                    if total > MAX_FILE_BYTES:
                                        raise ValueError("NOAA response exceeds 32 MiB per-file cap")
                                    used = sum(p.stat().st_size for p in cache.glob("*/*.grib2"))
                                    if used + total > MAX_CACHE_BYTES:
                                        raise ValueError(
                                            "Weather cache full (512 MiB); remove unused datasets locally"
                                        )
                                    stream.write(block)
                                stream.flush()
                                os.fsync(stream.fileno())
                        with temporary.open("rb") as stream:
                            start = stream.read(4)
                            stream.seek(-4, 2)
                            tail = stream.read(4)
                        if start != b"GRIB" or tail != b"7777":
                            raise ValueError("NOAA returned non-GRIB or truncated content (possibly HTML)")
                        # Decode and verify selected run/lead before committing to reusable cache.
                        decode_grib(temporary, request.run_utc, lead)
                        new_checksum = sha256_file(temporary)
                        if lead in pinned and new_checksum != pinned[lead]["sha256"]:
                            raise WeatherDomainError(
                                "NOAA source bytes changed; refusing to replace an immutable pinned dataset"
                            )
                        temporary.replace(path)
                        sync_directory(path.parent)
                        record = pinned.get(lead) or {
                            "file": path.name,
                            "sha256": new_checksum,
                            "size_bytes": total,
                            "source_uri": url,
                            "lead_hour": lead,
                            "retrieved_utc": utcnow().isoformat(),
                        }
                        atomic_json(metadata_path, record)
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in (
                            429,
                            500,
                            502,
                            503,
                            504,
                        ):
                            raise ValueError(
                                f"Selected NOAA run/lead unavailable: HTTP {exc.response.status_code}; no cycle substitution"
                            ) from exc
                        if attempt == 2:
                            raise ValueError(
                                f"NOAA connection failed: {type(exc).__name__}. Check network policy; no synthetic fallback"
                            ) from exc
                        for _ in range(10 * 2**attempt):
                            if cancelled():
                                raise Cancelled("Cancelled during NOAA retry backoff") from exc
                            time.sleep(0.1)
                    finally:
                        temporary.unlink(missing_ok=True)
                        _next_filter_request_monotonic = time.monotonic() + 10
            if record is None:
                raise WeatherDomainError("No verified metadata for the downloaded GRIB file")
            files.append(record)
            if sum(f["size_bytes"] for f in files) > budget_limit_bytes:
                raise ValueError("Verified weather sources exceed the explicit input-byte budget")
            progress(
                (index + 1) / estimate["files"],
                f"Cached verified lead f{lead:03d} ({index + 1}/{estimate['files']})",
            )
    manifest = {
        "schema_version": 1,
        "id": dataset_id,
        "provider": "NOAA_GFS",
        "origin": "forecast",
        "quality": "forecast_not_observation",
        "run_utc": request.run_utc.isoformat(),
        "request": request.model_dump(mode="json"),
        "grid_deg": 0.25,
        "member": "deterministic",
        "publication_time_utc": None,
        "retrieved_utc": previous.get("retrieved_utc", utcnow().isoformat()),
        "files": files,
        "source_uri": BASE,
        "licence": "NOAA US-government data; retain source attribution",
        "surface_assumption": "10m wind and 2m temperature used at surface boundary; not a boundary-layer model",
        "valid_start_utc": (request.run_utc + timedelta(hours=request.first_lead_hour)).isoformat(),
        "valid_end_utc": (request.run_utc + timedelta(hours=request.last_lead_hour)).isoformat(),
    }
    manifest["sha256"] = digest(manifest)
    atomic_json(directory / "manifest.json", manifest)
    return manifest


def decode_grib(path: Path, run: datetime, lead: int) -> dict:
    import eccodes as ec

    records: dict = {}
    latitudes = longitudes = None
    with path.open("rb") as stream:
        while (handle := ec.codes_grib_new_from_file(stream)) is not None:
            try:
                if ec.codes_get(handle, "gridType") != "regular_ll":
                    raise WeatherDomainError("Only regular latitude/longitude GFS grids are supported")
                if ec.codes_get(handle, "centre") != "kwbc":
                    raise WeatherDomainError("GRIB origin is not the selected NOAA/NCEP centre")
                if any(
                    abs(float(ec.codes_get(handle, key)) - 0.25) > 1e-8
                    for key in ("iDirectionIncrementInDegrees", "jDirectionIncrementInDegrees")
                ):
                    raise WeatherDomainError("GRIB spacing differs from the selected GFS 0.25 degree product")
                if ec.codes_get(handle, "numberOfPoints") > 1_000_000:
                    raise WeatherDomainError("GRIB grid exceeds the bounded regional point limit")
                if (
                    ec.codes_get(handle, "dataDate") != int(run.strftime("%Y%m%d"))
                    or ec.codes_get(handle, "dataTime") != run.hour * 100
                ):
                    raise WeatherDomainError("GRIB initialization differs from selected run")
                if int(ec.codes_get(handle, "endStep")) != lead or ec.codes_get(handle, "stepUnits") != 1:
                    raise WeatherDomainError("GRIB lead time differs from requested hourly lead")
                if ec.codes_get(handle, "stepType") != "instant":
                    continue
                kind, level, name = [
                    ec.codes_get(handle, key) for key in ("typeOfLevel", "level", "shortName")
                ]
                expected_units = {
                    "u": "m s**-1",
                    "v": "m s**-1",
                    "10u": "m s**-1",
                    "10v": "m s**-1",
                    "t": "K",
                    "2t": "K",
                    "gh": "gpm",
                    "pres": "Pa",
                    "sp": "Pa",
                    "orog": "m",
                }
                if name not in expected_units:
                    continue
                if ec.codes_get(handle, "units") != expected_units[name]:
                    raise WeatherDomainError(
                        f"Unsupported GRIB units for {name}: {ec.codes_get(handle, 'units')}"
                    )
                raw_lats = ec.codes_get_array(handle, "latitudes")
                raw_lons = ec.codes_get_array(handle, "longitudes")
                # regional downloaded lons transformed to [-180,180), then sorted.
                raw_lons = np.rad2deg(np.unwrap(np.deg2rad(raw_lons)))
                raw_lons = np.round(raw_lons - 360 * round(float(np.mean(raw_lons)) / 360), 10)
                la, lo = np.unique(raw_lats), np.unique(raw_lons)
                if len(la) * len(lo) != len(raw_lats):
                    raise WeatherDomainError("Nonrectangular or duplicated GRIB grid")
                if (
                    latitudes is not None
                    and longitudes is not None
                    and (not np.array_equal(la, latitudes) or not np.array_equal(lo, longitudes))
                ):
                    raise WeatherDomainError("GRIB fields have inconsistent geographic grids")
                latitudes, longitudes = la, lo
                vals = np.array(ec.codes_get_values(handle), dtype=float)
                missing = ec.codes_get(handle, "missingValue")
                vals[vals == missing] = np.nan
                array = np.full((len(la), len(lo)), np.nan)
                array[np.searchsorted(la, raw_lats), np.searchsorted(lo, raw_lons)] = vals
                key = (kind, int(level), name)
                if key in records:
                    raise WeatherDomainError(f"Duplicate GRIB field {key}")
                records[key] = array
            finally:
                ec.codes_release(handle)
    for level in LEVELS_HPA:
        for name in ("u", "v", "t", "gh"):
            if ("isobaricInhPa", level, name) not in records:
                raise WeatherDomainError(f"Missing required GFS field {name} at {level}hPa")
    surface_keys = {
        "u": ("heightAboveGround", 10, "10u"),
        "v": ("heightAboveGround", 10, "10v"),
        "temperature": ("heightAboveGround", 2, "2t"),
        "pressure": ("surface", 0, "sp"),
        "height": ("surface", 0, "gh"),
    }
    # GFS surface HGT may use shortName orog (metres interpreted as geopotential height for this model).
    if surface_keys["height"] not in records and ("surface", 0, "orog") in records:
        surface_keys["height"] = ("surface", 0, "orog")
    if surface_keys["pressure"] not in records and ("surface", 0, "pres") in records:
        surface_keys["pressure"] = ("surface", 0, "pres")
    try:
        surface = {key: records[value] for key, value in surface_keys.items()}
    except KeyError as e:
        raise WeatherDomainError(f"Required surface/near-surface field missing: {e}") from e
    return {
        "lats": latitudes,
        "lons": longitudes,
        "surface": surface,
        **{
            key: np.stack([records[("isobaricInhPa", level, name)] for level in LEVELS_HPA])
            for key, name in [("u", "u"), ("v", "v"), ("temperature", "t"), ("height", "gh")]
        },
    }


def read_manifest(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    saved_hash = manifest.pop("sha256")
    if digest(manifest) != saved_hash:
        raise WeatherDomainError("Weather manifest checksum mismatch")
    manifest["sha256"] = saved_hash
    request = DownloadRequest.model_validate(manifest["request"])
    leads = [f["lead_hour"] for f in manifest["files"]]
    if leads != list(range(request.first_lead_hour, request.last_lead_hour + 1)):
        raise WeatherDomainError("Weather manifest has missing, duplicate or unordered forecast leads")
    for record in manifest["files"]:
        if record["file"] != f"f{record['lead_hour']:03d}.grib2":
            raise WeatherDomainError("Weather manifest contains an invalid GRIB path")
    return manifest


def open_cached(
    directory: Path, *, legacy_surface_boundary: bool = False, at_time: datetime | None = None
) -> GridField:
    manifest = read_manifest(directory)
    request = DownloadRequest.model_validate(manifest["request"])
    files = manifest["files"]
    if at_time is not None:
        lead = (at_time - request.run_utc).total_seconds() / 3600
        if not request.first_lead_hour <= lead <= request.last_lead_hour:
            raise WeatherDomainError("Outside forecast valid-time horizon")
        first = min(int(math.floor(lead)), request.last_lead_hour - 1)
        files = [f for f in files if first <= f["lead_hour"] <= first + 1]
        request = request.model_copy(update={"first_lead_hour": first, "last_lead_hour": first + 1})
    if estimate_download(request)["unpacked_array_bytes"] > MAX_ARRAY_BYTES:
        raise WeatherDomainError("Cached weather exceeds memory bound")
    arrays = []
    for file in files:
        path = directory / file["file"]
        if sha256_file(path) != file["sha256"]:
            raise WeatherDomainError("Cached GRIB checksum mismatch")
        arrays.append(decode_grib(path, request.run_utc, file["lead_hour"]))
    if not arrays:
        raise WeatherDomainError("Empty weather dataset")
    for item in arrays[1:]:
        if not np.array_equal(item["lats"], arrays[0]["lats"]) or not np.array_equal(
            item["lons"], arrays[0]["lons"]
        ):
            raise WeatherDomainError("Forecast leads have inconsistent grids")
    stacked = {k: np.stack([a[k] for a in arrays]) for k in ("u", "v", "temperature", "height")}
    return GridField(
        [(request.run_utc + timedelta(hours=f["lead_hour"])).timestamp() for f in files],
        arrays[0]["lats"],
        arrays[0]["lons"],
        np.array(LEVELS_HPA) * 100,
        stacked["u"],
        stacked["v"],
        stacked["temperature"],
        stacked["height"],
        provenance=manifest,
        surface={k: np.stack([a["surface"][k] for a in arrays]) for k in arrays[0]["surface"]},
        legacy_surface_boundary=legacy_surface_boundary,
    )
