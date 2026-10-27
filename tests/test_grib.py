from datetime import UTC, datetime, timedelta
from pathlib import Path

import eccodes as ec
import httpx
import pytest

from packages.domain.models import DownloadRequest
from packages.meteo import gfs
from packages.meteo.field import WeatherDomainError
from scripts.make_synthetic_grib import make

RUN = datetime(2026, 10, 27, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def filter_clock(monkeypatch):
    from types import SimpleNamespace

    now = [100.0]

    def advance(seconds):
        now[0] += seconds

    monkeypatch.setattr(gfs, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=advance))
    monkeypatch.setattr(gfs, "_next_filter_request_monotonic", now[0])
    return now


def request():
    return DownloadRequest(
        run_utc=RUN,
        first_lead_hour=0,
        last_lead_hour=1,
        west_deg=9,
        east_deg=9.5,
        south_deg=45,
        north_deg=45.5,
    )


def test_real_decoder_on_explicitly_synthetic_grib_and_independent_point():
    path = FIXTURES / "synthetic-gfs-shaped-f000.grib2"
    result = gfs.decode_grib(path, RUN, 0)
    assert result["u"].shape == (len(gfs.LEVELS_HPA), 2, 2)
    with path.open("rb") as stream:
        handle = ec.codes_grib_new_from_file(stream)
        try:
            point = ec.codes_grib_find_nearest(handle, 45, 9)[0]
            assert result["u"][0, 0, 0] == pytest.approx(point["value"]) == 12
        finally:
            ec.codes_release(handle)
    assert result["surface"]["pressure"][0, 0] == 101325


def test_wrong_cycle_and_missing_field_are_rejected(tmp_path):
    path = FIXTURES / "synthetic-gfs-shaped-f000.grib2"
    with pytest.raises(WeatherDomainError, match="initialization"):
        gfs.decode_grib(path, RUN + timedelta(hours=6), 0)
    with pytest.raises(WeatherDomainError, match="lead"):
        gfs.decode_grib(path, RUN, 1)
    broken = tmp_path / "missing.grib2"
    make(broken, 0, omit=("isobaricInhPa", 250, "u"))
    with pytest.raises(WeatherDomainError, match="Missing required"):
        gfs.decode_grib(broken, RUN, 0)


def test_download_cache_checksum_and_resume_with_synthetic_http_fixture(tmp_path, monkeypatch, filter_clock):
    original = httpx.Client
    calls = []

    def handler(req):
        calls.append(str(req.url))
        lead = int(req.url.params["file"][-3:])
        content = (FIXTURES / f"synthetic-gfs-shaped-f{lead:03d}.grib2").read_bytes()
        return httpx.Response(200, content=content, headers={"Content-Type": "application/octet-stream"})

    monkeypatch.setattr(
        gfs.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    manifest = gfs.fetch_subset(request(), tmp_path, lambda *_: None)
    field = gfs.open_cached(tmp_path / manifest["id"])
    state = field.get_state(45.125, 9.125, 12500, RUN + timedelta(minutes=30))
    assert state.u_ms == 12
    assert state.v_ms == 3
    gfs.fetch_subset(request(), tmp_path, lambda *_: None)
    assert len(calls) == 2  # Verified cached files reused, no duplicate network download.
    assert "var_UGRD=on" in calls[0]
    path = tmp_path / manifest["id"] / "f000.grib2"
    path.write_bytes(b"corrupted")
    with pytest.raises(WeatherDomainError, match="checksum"):
        gfs.open_cached(path.parent)


@pytest.mark.parametrize("status,content", [(200, b"<html>no data</html>"), (404, b"missing")])
def test_noaa_errors_never_fall_back_to_synthetic(tmp_path, monkeypatch, status, content, filter_clock):
    original = httpx.Client
    monkeypatch.setattr(
        gfs.httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, content=content)), **kw
        ),
    )
    with pytest.raises((ValueError, OSError)):
        gfs.fetch_subset(request(), tmp_path, lambda *_: None)
    assert not list(tmp_path.glob("*/manifest.json"))


def test_noaa_required_pacing_is_cancellable(monkeypatch, filter_clock):
    from packages.domain.models import Cancelled

    start = filter_clock[0]
    monkeypatch.setattr(gfs, "_next_filter_request_monotonic", start + 10)
    gfs.wait_for_filter_slot(lambda: False)
    assert filter_clock[0] >= start + 10
    start = filter_clock[0]
    monkeypatch.setattr(gfs, "_next_filter_request_monotonic", start + 10)
    with pytest.raises(Cancelled):
        gfs.wait_for_filter_slot(lambda: filter_clock[0] >= start + 0.1)
    assert filter_clock[0] < start + 1


def test_finalized_cache_repair_retains_immutable_manifest(tmp_path, monkeypatch, filter_clock):
    original = httpx.Client

    def handler(req):
        lead = int(req.url.params["file"][-3:])
        return httpx.Response(
            200, content=(FIXTURES / f"synthetic-gfs-shaped-f{lead:03d}.grib2").read_bytes()
        )

    monkeypatch.setattr(
        gfs.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    manifest = gfs.fetch_subset(request(), tmp_path, lambda *_: None)
    directory = tmp_path / manifest["id"]
    (directory / "f000.grib2").write_bytes(b"corrupt")
    restored = gfs.fetch_subset(request(), tmp_path, lambda *_: None)
    assert restored == manifest
    assert gfs.sha256_file(directory / "f000.grib2") == manifest["files"][0]["sha256"]


def test_source_change_cannot_replace_a_finalized_cache(tmp_path, monkeypatch, filter_clock):
    original = httpx.Client
    changed = [False]
    mutant = tmp_path / "mutant.grib2"
    with (FIXTURES / "synthetic-gfs-shaped-f000.grib2").open("rb") as src, mutant.open("wb") as out:
        while (h := ec.codes_grib_new_from_file(src)) is not None:
            try:
                if ec.codes_get(h, "shortName") == "u":
                    ec.codes_set_values(h, [99.0] * 4)
                ec.codes_write(h, out)
            finally:
                ec.codes_release(h)

    def handler(req):
        lead = int(req.url.params["file"][-3:])
        content = (
            mutant.read_bytes()
            if changed[0] and lead == 0
            else (FIXTURES / f"synthetic-gfs-shaped-f{lead:03d}.grib2").read_bytes()
        )
        return httpx.Response(200, content=content)

    monkeypatch.setattr(
        gfs.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    manifest = gfs.fetch_subset(request(), tmp_path, lambda *_: None)
    directory = tmp_path / manifest["id"]
    (directory / "f000.grib2").write_bytes(b"corrupt")
    changed[0] = True
    with pytest.raises(WeatherDomainError, match="immutable pinned"):
        gfs.fetch_subset(request(), tmp_path, lambda *_: None)
    assert gfs.read_manifest(directory)["sha256"] == manifest["sha256"]
    assert (directory / "f000.grib2").read_bytes() == b"corrupt"


def test_forecast_window_can_start_after_initialization_without_shortening_72h():
    from pydantic import ValidationError

    window = DownloadRequest(run_utc=RUN, first_lead_hour=6, last_lead_hour=78)
    estimate = gfs.estimate_download(window)
    assert estimate["files"] == 73
    assert estimate["minimum_filter_wait_seconds"] == 720
    assert estimate["unpacked_array_bytes"] <= estimate["memory_limit_bytes"]
    assert "f078" in gfs.subset_url(window, 78)
    with pytest.raises(ValidationError, match="at most 72 hours"):
        DownloadRequest(run_utc=RUN, first_lead_hour=0, last_lead_hour=73)
    with pytest.raises(ValidationError):
        DownloadRequest(run_utc=RUN, first_lead_hour=119, last_lead_hour=121)
    assert DownloadRequest(run_utc=RUN, first_lead_hour=119, last_lead_hour=120).last_lead_hour == 120


def test_later_hourly_grib_leads_keep_time_identity_and_decoder_contract(tmp_path):
    """Explicit synthetic messages exercise f078/f079; no later live NOAA download is claimed."""
    from packages.domain.models import digest

    request = DownloadRequest(
        run_utc=RUN,
        first_lead_hour=78,
        last_lead_hour=79,
        west_deg=9,
        east_deg=9.5,
        south_deg=45,
        north_deg=45.5,
    )
    folder = tmp_path / "later-window"
    folder.mkdir()
    files = []
    for lead in (78, 79):
        path = folder / f"f{lead:03d}.grib2"
        make(path, lead)
        files.append(
            {
                "file": path.name,
                "lead_hour": lead,
                "sha256": gfs.sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    metadata = {
        "id": "later-window",
        "provider": "SYNTHETIC_GRIB_TEST",
        "request": request.model_dump(mode="json"),
        "files": files,
    }
    metadata["sha256"] = digest(metadata)
    gfs.atomic_json(folder / "manifest.json", metadata)
    field = gfs.open_cached(folder, at_time=RUN + timedelta(hours=78.5))
    state = field.get_state(45.125, 9.125, 12500, RUN + timedelta(hours=78.5))
    assert state.u_ms == 12 and state.v_ms == 3
    assert state.temporal_weight == 0.5
    assert state.valid_before_utc == (RUN + timedelta(hours=78)).isoformat()
    assert state.valid_after_utc == (RUN + timedelta(hours=79)).isoformat()


def test_filter_fetches_and_retries_obey_noaa_ten_second_minimum(tmp_path, monkeypatch):
    """Independent policy check with a private virtual clock and synthetic HTTP bodies."""
    from types import SimpleNamespace

    now = [100.0]

    def advance(seconds):
        now[0] += seconds

    monkeypatch.setattr(gfs, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=advance))
    monkeypatch.setattr(gfs, "_next_filter_request_monotonic", now[0])
    original = httpx.Client
    observed = []

    def handler(req):
        observed.append(now[0])
        if len(observed) == 1:
            return httpx.Response(503, content=b"explicit test-only NOAA failure")
        lead = int(req.url.params["file"][-3:])
        return httpx.Response(
            200, content=(FIXTURES / f"synthetic-gfs-shaped-f{lead:03d}.grib2").read_bytes()
        )

    monkeypatch.setattr(
        gfs.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    manifest = gfs.fetch_subset(request(), tmp_path, lambda *_: None)
    assert len(manifest["files"]) == 2
    assert len(observed) == 3
    assert all(b - a >= 10 for a, b in zip(observed, observed[1:], strict=False))
