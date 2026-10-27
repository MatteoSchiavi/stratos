# Second P1 review — 27 October 2026

This pass stays within the atmospheric-input/trajectory/recovery scope. Earlier numerical and NOAA evidence remains preserved; no hardware or flight-readiness claim follows.

## Selected weaknesses

1. Altitude-only exploration cannot distinguish an isobaric surface from a prescribed geometric altitude. Add sampling of actual retained pressure levels, including their varying model heights, while rejecting below-ground/nonphysical samples.
2. Sparse arrows alone hide speed/temperature structure. Add bounded sampled scalar grids and tested marching-squares contours. Missing cells must break contours, ambiguous saddles need a defined rule, and displayed interpolation must not imply finer model resolution.
3. Wind glyphs can span the world at the antimeridian. Use consistent split line geometry and explicit endpoint points.
4. Backup manifests verify copied files, but concurrent queued work can make a multi-file snapshot incomplete. Inspect active-job behavior and tighten the supported quiet-state contract.

## Architecture

Keep existing altitude sampling and schema1 replay untouched. Add a pressure-level sampler alongside them, with typed plane selection in the read-only explorer. A pure NumPy contour module emits GeoJSON from finite grid cells; its geometry is tested independently of the UI. No additional dependency or network source is needed. The inspector exports the exact displayed slice and its forecast provenance.

Verification results and remaining limits will be appended after implementation. Native Windows/8GB-host qualification, full72h testing, 3D volume display and later phases remain separate work.

## Implemented findings

- Actual retained pressure surfaces now report their varying GFS heights, with surface-pressure/terrain masks. Wind-speed/temperature contours use a bounded17/25/33 display grid, explicit missing-cell gaps and an asymptotic saddle decider. Exact critical crossings terminate at their saddle. Native0.25° resolution and sampled ranges remain distinct from display interpolation.
- Wind glyphs split at the dateline and retain independent endpoint points. Probes, source times, units and inspected-slice JSON hashes remain explicit. Startup scientific-code identity is checked before and after read-only scientific analysis.
- Saved-record metadata/IDs are checked against immutable manifests as well as scientific output/config hashes. Backups check actual pinned raw forecasts and reconstruct missing redundant exports only from a verified authoritative database. Archive verification is read-only; restore targets must be new directories.
- Download estimates retain their original request fingerprint. Late saves preserve newer edits; stale forecast responses cannot overwrite a changed selection. Native step validation formerly rejected the default6h duration; continuous mission inputs now accept valid precision while integer controls remain discrete.
- Browser verification uses its own loopback8001 API/worker and temporary database. The planning workspace on8000 was checked before/after and remained unchanged.
- Absolute lead limits and window duration are separated: up to72h/73files within hourly leads0–120. NOAA pacing alone requires at least720s for73files; download allowance is30min. A private-clock regression checks the10s minimum across failed attempts/retries; pacing uses the actual monotonic deadline.
- Saved-study comparison aligns two immutable predictions by elapsed time or UTC within their shared horizon. It reports sampled horizontal/height separation, changed inputs, cycle/solver/source identities and a content hash. WGS84 geodesic interpolation handles the dateline. It performs no new weather request or integration and supplies no measured-error/probability claim.

## Portable real inputs

Two retained NOAA windows share27 October2026 18–19UTC, ROI5–23E/37–55N:

| Cycle / leads | Cache identity | Exact raw bytes |
| --- | --- | --- |
| 06UTC f012–f013 | `gfs_93cbbb02f96a7b9d20dd2a7d` | 1,515,316 |
| 12UTC f006–f007 | `gfs_fbd570fc6048b21071e005e0` | 1,466,028 |

These are byte-for-byte retained subsets of previously downloaded real NOAA files. No GRIB values were re-encoded or synthesized. Original source URLs/retrieval metadata and complete parent provenance are retained in each fixture directory. Startup imports them with the earlier dated regional reference, entirely offline. They are forecast references, not current observations on future install dates.

The controlled-cycle regression starts the actual API/worker, calculates both1h float-only studies at12,500m and the same45.05N/9.70E start, then compares their shared UTC path. Only `weather.dataset_id` differs between configurations. Its end separation is independently checked with GeographicLib. `tests/test_cross_cycle_reference.py` reproduces this workflow from a fresh checkout without Internet.

## Verification commands

```sh
.venv/bin/ruff check packages services scripts tests
.venv/bin/ruff format --check packages services scripts tests
.venv/bin/mypy packages services --explicit-package-bases
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.reproduce
cd apps/web
npm run lint
npm run build
STRATOS_CHROMIUM=/usr/bin/chromium npm run test:e2e
```

Independent references include closed-form/equivalent GeographicLib solver checks, actual ecCodes isobaric-point extraction, analytic contour planes/saddles/masks, dateline path interpolation and UTC/elapsed alignment. The original NOAA float/ascent golden outputs still reproduce with exact hashes and zero coordinate differences in this instance.

Earlier in this pass,90 backend tests and11 isolated browser scenarios passed before retaining the additional common-time NOAA fixtures. The expanded suite and publishing/clean-install evidence are recorded below after their final execution. Frontend lint/TypeScript/production build passed; the main bundle is about322kB, with the larger lazy MapLibre chunk still disclosed by the bundler.

Live NOAA discovery was attempted through the application's real endpoint and returned502/ProxyError under the active cloud destination policy. Official domains are preserved in the configuration draft; cached real inputs require no network. No proxy/TLS bypass is used.

## Remaining limitations

Full real72h qualification, native Windows, an independent8GB host and a full3D weather volume remain open. Automatic cache eviction, SSE and numerical checkpoints are deferred. All trajectories remain prescribed, uncalibrated L0 transport; no lift/survival, radio/connectivity, power, balloon data recovery or launch-readiness assessment is claimed. The new restore tool recovers local engineering evidence, not balloon telemetry.

Final expanded checks: **91 backend tests passed in27.76s**, one upstream Starlette/httpx deprecation warning; lint/format passed42 Python files and mypy passed24 source files. **All11 isolated Chromium scenarios passed in59.9s**. Frontend lint/TypeScript/build passed. No source changes were made after these feature checks; publishing/clean-install evidence follows below.
