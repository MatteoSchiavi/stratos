# STRATOS · Mission engineering

A free, local-first engineering workspace for one atmospheric balloon mission. This milestone implements the P0 foundation and a working P1 **L0 prescribed-profile** trajectory workflow. It does **not** establish flight readiness.

The complete supplied specification is preserved in [docs/STRATOS_ENGINEERING_SPEC_V2.md](docs/STRATOS_ENGINEERING_SPEC_V2.md). Read [ARCHITECTURE.md](ARCHITECTURE.md) for the pre-implementation audit, [DECISIONS.md](DECISIONS.md) for tradeoffs, and [PROJECT_STATUS.md](PROJECT_STATUS.md) for verified capabilities and remaining work.

Complete installation, configuration, daily workflow and recovery instructions: [INSTALL_AND_USE.md](INSTALL_AND_USE.md).

## Run locally

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node 22.12+ (Node 24 tested), npm, a browser with WebGL2. No account, API key, Docker, paid service or hardware is required.

From the repository root (in this managed cloud workspace, first set `export UV_CACHE_DIR=/workspace/stratos/.cache/uv`):

```sh
uv sync --frozen
cd apps/web
npm ci
npm run build
cd ../..
uv run --frozen python -m scripts.dev
```

After scientific Python or dependency changes, restart the launcher. The worker pins its startup code and refuses calculations from a stale runtime; health reports `restart_required`. Frontend-only changes do not invalidate a scientific run.

The launcher binds the API and compiled UI to loopback port **8000** and starts one durable worker. Open that port in your local browser. Stop the launcher with Ctrl+C to stop its children. `--port 8001` selects a different API/UI port. For frontend hot reload, keep API/worker running, then run `npm run dev` in `apps/web`; Vite proxies `/api` to port 8000.

The same commands use uv on Windows; native Windows runtime has not been verified in this cloud instance. Python interpreter invocations can also use `.venv/bin/python` on Linux or `.venv\Scripts\python.exe` on Windows. Native ecCodes 2.50.0 is explicitly supplied by `eccodeslib` on Linux; the ecCodes Windows wheel's bundled decoder still needs Windows verification.

## First workflow: entirely offline

1. First startup imports bundled, explicitly dated real NOAA references (with checksums), loads `mission.yaml`, and enqueues a real calculation with a **synthetic constant-wind field** (U=12 m/s east, V=3 m/s north). After dependency installation, the app, basemap, mission and calculation need no Internet.
2. Inspect the predicted path, scrub the altitude timeline with mouse or arrow keys, and examine pressure, temperature, wind and altitude units in the sample inspector. Map zoom, fit and country-boundary controls work locally.
3. In **Plan**, change launch coordinates/time and the prescribed profile. Mass is recorded but deliberately does **not** affect L0 advection. Save a revision, or **Run simulation** to save and calculate in one action.
4. **Analyze** reopens saved results. **Run evidence** exposes configuration/output/source/manifest hashes. Export complete JSON (all samples plus manifest), CSV, antimeridian-safe 2D GeoJSON, or mission YAML. Stored-output hashes are checked before reopening/exporting.

Every track is simulated and uncalibrated. Synthetic weather is watermarked **DEMO DATA**. The mission record remains in DEMO mode even when its wind source is a real NOAA forecast. Replay, hardware-test and live records cannot be simulated by this release.

## Real NOAA GFS workflow

1. In **Simulate → Weather inputs**, discover published cycles or specify an exact 00/06/12/18 UTC initialization. Discovery checks NOMADS directories for actual files; it does not assume every recent cycle is complete.
2. Select an explicit non-dateline-crossing ROI and consecutive hourly leads within 0–120h, spanning at most72h (73 files). Estimate download/memory first; then download. The default cropped 48h estimate includes pressure-level U/V/T/HGT and surface/near-surface fields. Transfers are serial, bounded, cancellable and have retry/backoff plus the NOAA-documented ten-second wait between filter fetches. No silent change of cycle or provider.
3. In **Plan**, select the cached GFS dataset. Its first valid time becomes the proposed start; review this and the complete profile duration. Verify initial altitude against site/model terrain. To study a floating balloon independently of ascent, set initial altitude equal to target altitude.
4. Run, inspect the selected run and temporal brackets, export, and reopen. The API preflights the whole time horizon and initial terrain/altitude state. Missing files, cells, levels or altitude coverage stop the calculation. A crop exit either stops explicitly or, when enabled in Plan for schema2, triggers bounded same-cycle adjacent-crop acquisition with overlap checks. Segment and input-byte quotas remain blocking. **No partial route is reported as a complete prediction.**

**Verified real-data example:** GFS initialization **2026-10-27 06:00 UTC**, hourly leads **f006–f008**, ROI **5–20°E / 40–52°N**. The running adapter downloaded 1,253,205 bytes and calculated a 64.7007 km one-hour float track and a 78.2701 km prescribed ascent/float track. Both original GRIB inputs and complete outputs are retained under `tests/fixtures/noaa-gfs-20261027-06-regional/` and `docs/examples/`. A second tiny 36,534-byte crop supports decoder regression tests. Three point checks agree with direct ecCodes extraction; the tiny crop also agrees with cfgrib/xarray. Run `uv run --frozen python -m scripts.reproduce` to reproduce both regional examples **without Internet**.

NOAA was initially blocked by network policy; access subsequently became available and the real workflow was exercised. Official hosts `nomads.ncep.noaa.gov` and `www.nco.ncep.noaa.gov` are saved in the environment draft. Future runs still require those hosts to download new forecasts; no secret is needed. Cached inputs remain usable offline. See `docs/verification.md` for exact evidence and hashes.

## Engineering boundaries

* New missions use schema2: fourth-order WGS84 latitude/longitude curvature rates include the prescribed height (`M+h`, `N+h`). Independent equatorial and meridional references validate the solver. Ground-track distance is accumulated on integration steps; horizontal air distance is integrated separately, without changing the path when display-sample cadence changes. Schema1 retains the original reference-surface solver and its golden hashes for replay. A precise local geoid offset is still not supplied.
* Vertical motion is prescribed ascent/float/optional descent. It does not model attainable float, balloon leakage, burst, icing, thermal lift or payload endurance.
* GRIB HGT geopotential metres are converted with standard reference radius 6,356,766m. Actual model height columns determine vertical wind/temperature interpolation; pressure is interpolated logarithmically between height surfaces. No pressure=altitude identity or weather extrapolation.
* GFS surface winds are the 10m product and temperatures the 2m product; using them as a surface boundary is an explicit approximation. Coarse GFS terrain is not a landing/recovery DEM. Descent ends at configured flat ground only.
* Cached weather exploration provides selectable UTC/altitude or actual retained pressure surfaces, wind-speed/temperature contours, a cursor-selected vertical pressure-level profile and explicit invalid-cell counts. Pressure surfaces use their actual varying model heights; below-ground levels and missing grid cells are masked. Contour grids are bounded17/25/33 display samples per axis and add no native model resolution. Each inspected slice has a content hash, loaded scientific-code identity and complete JSON export. It decodes at most two hourly leads for a request. Vector length is a disclosed ten-minute displacement scale, not a predicted track or coverage radius. An invalid probe retains the last valid view with an explicit error.
* No forecast-at-issue-time historical verification, actual ensemble spread, 3D weather-volume display, RF connectivity, recovered-byte budget, power state machine, firmware, imaging or legal-readiness assessment is implemented. These remain explicit tasks.

## Persistence and resource limits

SQLite WAL with FULL synchronous writes and Alembic migration stores immutable mission revisions, durable jobs and finalized outputs. An additional atomic JSON result is retained. Raw GRIB files have SHA-256 sidecars, exact request URLs and retrieval timestamps. Manifest hashes include normalized configuration, weather files, scientific outputs, source tree, available commit, package versions, Python/platform identity and RNG usage (none for this deterministic model).

One worker per data directory is enforced by an OS lock. At most 8 active jobs are queued. A worker restart marks unfinished running jobs **interrupted**, ready for explicit resubmission. Verified downloaded files are reused; numerical checkpoint continuation is not implemented. Wall-clock budgets: 30min weather download (NOAA pacing alone takes12min for73 files),15min expanding-weather study,2min cached/fixed-region simulation. Maximum 72h total profile, 384 MiB decoded-array estimate, 32 MiB per response and 512 MiB total GRIB cache. Decoded schema2 weather uses a three-window LRU; the read-only API keeps at most two slices. Automatic spatial expansion is opt-in, at most16 segments /128MiB of verified source inputs; reused cached bytes also count. Full source identities and per-unit overlap tolerances/errors are retained. Remove unused cache directories manually only when no jobs need them; automatic disk eviction is deferred.

Use `uv run --frozen python -m scripts.backup --output /absolute/path/outside-live-data/new-backup` for a consistent SQLite backup, raw weather and saved results with file checksums. It refuses an absent/uninitialized source, active jobs or an existing target. Required raw forecasts and saved-result identifiers/labels/hashes are validated against the database snapshot. Missing/damaged redundant JSON exports can be reconstructed from verified authoritative database records; originals are preserved.

Verify an archive without modifying it:
```sh
uv run --frozen python -m scripts.verify_backup --backup /absolute/path/to/backup
```
To restore into a **new, nonexistent** directory, append `--restore-to /absolute/path/to/new-data`. The tool verifies before and after copying, refuses overwrites, and marks incomplete restores. Set `STRATOS_DATA_DIR` to the new directory before starting both services. Keep the original archive closed and unchanged.

Default runtime state is in gitignored `data/`. Set `STRATOS_DATA_DIR` before starting **both** API and worker for another directory. Back up the entire directory with the services stopped (or use SQLite's backup API); copying only the SQLite main file while WAL is active is not a consistent backup. JSON exports supplement, rather than replace, raw-weather retention.

Write requests reject cross-origin browser requests and payloads above 64 KiB. Upstream URLs are fixed by the adapter, not supplied by callers. This is a single-user loopback application; external hosting requires an authenticated reverse proxy/TLS and a separate security review.

## Verification

```sh
uv run --frozen ruff check packages services scripts tests
uv run --frozen ruff format --check packages services scripts tests
uv run --frozen mypy packages services --explicit-package-bases
uv run --frozen pytest -q
cd apps/web
npm run typecheck
npm run lint
npm run build
npx playwright install chromium
npm run test:e2e
```

The browser suite starts a separate API/worker on loopback8001 with a new temporary data directory. It does not reuse the planning server/database on8000. `STRATOS_E2E_PORT` selects another test port; `STRATOS_E2E_DATA_DIR` must be test-only. In this cloud instance, use `STRATOS_CHROMIUM=/usr/bin/chromium` instead of installing a second browser; `STRATOS_CAPTURE=1` saves desktop/mobile screenshots in `docs/screenshots/`.

Regenerate the explicitly synthetic GRIB fixtures with `uv run --frozen python -m scripts.make_synthetic_grib`. OpenAPI is served at `/openapi.json` and interactive API documentation at `/docs`. See [docs/API.md](docs/API.md) for P1 routes and polling semantics. CI runs the scientific/API checks, client checks and browser smoke workflow; no live NOAA call is required for deterministic CI.

The 48h endurance procedure is `uv run --frozen python -m scripts.validate_long_forecast --dataset gfs_956c52d52a69009dd016a2fd --offline` in the prepared cloud instance. Its initial crop and adjacent segments are retained in the local cache; it intentionally refuses network repair in offline mode. See `docs/RESEARCH_REVIEW.md` and `docs/REVIEW_VERIFICATION.md` for the new audit and measured results.

Map attribution and source licences are in [docs/SOURCES.md](docs/SOURCES.md). No external map tiles, font server, analytics or simulated live feed.

The second P1 review adds pressure-surface scrutiny, tested contour topology, archive verification/restore, saved-label consistency and protection against delayed UI responses. Findings and new verification evidence: [docs/P1_SECOND_REVIEW.md](docs/P1_SECOND_REVIEW.md).

Analyze also compares saved predictions with explicit elapsed/UTC alignment, WGS84 interpolation, sampled separation/height metrics, configuration differences and a source-hashed JSON export. These are scenario sensitivity tools between uncalibrated predictions.

Offline controlled-cycle inputs now retain exact NOAA bytes for06UTC f012–f013 and12UTC f006–f007, both valid27 October2026 18–19UTC. Their byte-for-byte subset provenance is retained beside the fixtures; this is dated forecast evidence, not current observations.
