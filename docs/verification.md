Follow-up verification of the expanded P1 implementation: [REVIEW_VERIFICATION.md](REVIEW_VERIFICATION.md). This document retains the initial milestone evidence.

# Verification — 27 October 2026

Current machine: Linux x86-64, Python 3.12.14, Node 24.19.0, approximately 33 GiB RAM. Native Windows and an 8GB host remain untested.

| Executed check | Result |
| --- | --- |
| `bash scripts/install.sh` | Frozen uv install, npm clean install, production build, repeatable Alembic migration succeeded |
| `.venv/bin/ruff check packages services scripts tests` | Pass |
| `.venv/bin/ruff format --check packages services scripts tests` | Pass |
| `.venv/bin/mypy packages services --explicit-package-bases` | Pass, 16 files |
| `.venv/bin/python -m pytest -q` | **36 passed**, none failed/skipped/expected-failure; one upstream Starlette/httpx deprecation warning |
| `npm run lint`, `npm run typecheck`, `npm run build` in `apps/web` | Pass; large MapLibre-containing JS chunk warning (~1.37MB uncompressed) remains a performance limitation |
| `STRATOS_CHROMIUM=/usr/bin/chromium STRATOS_CAPTURE=1 npm run test:e2e` | **4 passed in 39.0s**: offline map/timeline/boundaries; edit→run→save→export→refresh→reopen; explicit provider error/estimate guard; mobile/keyboard/no overflow |
| Separate actual NOAA browser workflow | Real track rendered with forecast provenance, no synthetic watermark, correct final coordinates, identical exported/reopened JSON, 390px mobile layout and no page errors |
| Actual launcher stop/restart | Complete saved simulation JSON identical after stopping/restarting only our own services |
| `.venv/bin/python -m scripts.reproduce` | Both retained real-weather examples reproduce offline; exact output hashes match here (see `reproduction-results.json.txt`) |

CI is configured but remote CI has not run; no commit/push was requested. The browser provider-error test uses an explicitly mocked 502, separately from successful real NOAA calls. Offline browser testing blocks all non-loopback HTTP and verifies none are required; it does not claim new forecasts can download offline.

## Scientific and integrity coverage

- No-wind stationary; constant-wind equatorial/east and northward WGS84 displacement against GeographicLib (<0.02m tolerance for one-hour references); dateline/high latitudes; time-step convergence under sheared wind.
- Prescribed ascent/float/descent events and configured ground; analytic space/time/height interpolation; log-pressure recovery; geometric/geopotential round trip.
- NaN/missing cells, missing hourly lead, invalid altitude/time/ROI, below-terrain states and future initialization rejected without extrapolation.
- Actual native GRIB decode; run/lead and required-field checks; cache reuse and checksum corruption rejection; cfgrib/xarray and direct ecCodes point extraction on a real NOAA crop.
- Real regional forecast → original float/ascent outputs reproduced offline with retained inputs; cross-platform acceptance allows 1e-9° coordinate and 1e-4 m distance difference while reporting exact hash equality separately.
- Mission YAML/revisions, manifest/output hashes, job cancellation/interruption, new app instance recovery, cross-origin writes and oversized imports.

These cases establish computational behavior, not flight forecast skill or envelope performance. Initialization-before-launch checks do not establish issued-at-time availability when publication time is unknown.

## Actual NOAA calls and data

Discovery: `GET https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/` plus selected date/cycle/atmos directory listings. Observation retained in `noaa-access-check.json`. The initial proxy denial later resolved; successful service responses establish actual access.

Filter: `GET https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl`, files `gfs.t06z.pgrb2.0p25.f006`/f007/f008, directory `/gfs.20261027/06/atmos`, UGRD/VGRD/TMP/HGT/PRES, requested isobaric and near-surface levels, ROI 5–20°E / 40–52°N. **Initialization 2026-10-27T06:00:00Z; valid 12/13/14 UTC; deterministic 0.25° member.** Full encoded URLs, retrieval timestamps and raw checksums are in `tests/fixtures/noaa-gfs-20261027-06-regional/manifest.json`.

- Regional raw inputs: **1,253,205 bytes**; prior estimate 1,739,598 bytes, explicitly approximate.
- Tiny additional crop: 9.5–10°E/44.75–45.25°N, f006/f007, **36,534 bytes** retained in a separate fixture directory.
- Three independent points at 45°N / 10°E / 20000 Pa: U/V absolute error≤5.4e-15 m/s, temperature 0 K, pressure≤1.9e-11 Pa. Exact vectors in `examples/noaa-point-checks.json`.
- Float output: **64,700.703589m /3,600s /31samples**, SHA-256 `cd352deeb9bd741a3c018eff2d0a6e5445665ef3112c2fae202528fee8953770`.
- Prescribed ascent/float: **78,270.110094m /6,895s /60samples**, SHA-256 `0f28299072a4c9c3065a17767123f6210b1853b7edf02220339499def37508e8`.

Original inputs and outputs are retained, independent of rolling NOAA archive retention. Original manifests keep source hashes and `git_commit=null` (unborn repository). Later documentation/tool changes do not rewrite historical manifests.

## Screenshots and scope

`screenshots/trajectory-desktop.png` / `trajectory-mobile.png`: synthetic DEMO workflows. `screenshots/noaa-trajectory-desktop.png` / `noaa-trajectory-mobile.png`: actual NOAA-derived prediction, still simulated/uncalibrated. No measured flight telemetry. Natural Earth basemap is coarse public-domain geography, not terrain or permissions. Basemap SHA-256: `6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f`.

Unrun gates: full 48–72 h resource test, 8GB host, Windows, observed-flight skill, moving ROI/weather explorer, hardware/RF/power/data-recovery/readiness and later-phase acceptance B–H. An assumed 150 m start is not a surveyed/approved launch site. See `PROJECT_STATUS.md` and `NEXT_CODEx_TASK.md`.
