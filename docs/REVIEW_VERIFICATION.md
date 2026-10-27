Second review and current verification: [P1_SECOND_REVIEW.md](P1_SECOND_REVIEW.md). The evidence below remains the earlier recorded milestone.

# Engineering review verification — 27 October 2026

This extends the initial [verification report](verification.md). It verifies software behavior and retained forecast calculations; it does not measure balloon endurance, trajectory forecast skill, RF connectivity, data recovery or power reliability. P2–P7 remain deferred.

## Scientific changes and independent checks

New configuration schema2 uses WGS84 curvature radii at prescribed height: north velocity divided by `M+h`, east velocity divided by `(N+h)cos(latitude)`. Tests compare equatorial angular displacement with its closed form and meridional motion with independent GeographicLib meridional arcs plus SciPy root solving. Ground distance is integrated on the numerical mesh; horizontal air distance is a separate RK4 state. Changing display snapshot cadence leaves the numerical endpoint, total ground distance and air distance unchanged. Profile transitions remain exact events. Geometric MSL height approximates ellipsoidal height until a geoid/site model is supplied.

Schema1 remains a separate preserved implementation. Offline replay of the original one-hour float and ascent/float NOAA examples still yields **zero coordinate difference and the original exact output hashes** in this environment. `docs/reproduction-results.json.txt` records both. New diagnostic fields are not retroactively inserted into old results.

Input validation checks NOAA/NCEP centre, quarter-degree grid, initialization/lead/valid times, field units and safe finalized manifest paths/checksums. Below-ground pressure levels are excluded; missing above-ground data remains an error. Same-cycle adjacent crops are compared in overlap at two points with per-unit packing tolerances. Those tolerances describe GRIB consistency, not meteorological uncertainty.

## Real 48-hour study

- Start 2026-10-27 16UTC at assumed 45.05N/9.70E, **prescribed constant12,500m geometric MSL**, 48h, deterministic GFS 2026-10-27 06UTC.
- Initial ROI5–23E/37–55N, f010–f058:49 files /35,414,675 bytes. Adjacent acquisition used16 total source segments /46,715,809 verified raw bytes, all the same cycle/member/grid. The16-segment/128MiB request budget was explicit.
- Final saved API/worker record `db683209-a61d-4d0d-91c6-ccc5006bfadc`,1,441 samples,172,800s. Ground distance **4,596,333.905296m**, horizontal air distance4,605,342.029253m. Final point31.4258057482N/51.0156450521E at29 October16UTC.
- Output SHA256 `78b7a99d9556bb35db42643e3ccb0236152766518f921c3f1ce042b58654fb6b`. Complete record: [noaa-48h-simulation.json](examples/noaa-48h-simulation.json). Each sample identifies its actual weather segment; manifests retain all raw requests/hashes and per-unit overlap checks.
- The durable production job completed27 October17:06:47UTC, after the fresh download job. API remained responsive while the separate worker calculated. This saved run uses the final runtime identity guard; loaded scientific code/dependencies cannot change before publication.

A preceding command-line endurance experiment measured **535.459s**, peak222,324KiB RSS with a6GiB address-space cap (mixed cached/new adjacent inputs). Its cached repeat measured **115.251s**, peak223,884KiB (218.637MiB). Both had identical physical coordinates/distances and exact output hash `62d6e56e2c25241d1339de069078c45418278dab684ff8118727bd57dc825782`. This earlier output predates the additional per-sample segment IDs and unit-specific overlap metadata; its hash intentionally differs from the final saved record. These are Linux process measurements on a larger host, not a native8GB-laptop qualification.

The large raw cache is retained locally and backed up, rather than added to the small repository fixture set. An exact cached replay without HTTP is:
```sh
export UV_CACHE_DIR=/workspace/stratos/.cache/uv
uv run --frozen python -m scripts.validate_long_forecast --dataset gfs_956c52d52a69009dd016a2fd --offline
```
This requires the prepared instance/backup with all exact crops. An independent fresh checkout still reproduces both smaller real legacy examples entirely offline using repository fixtures.

## Fresh current-cycle download

The actual queue fetched GFS **2026-10-27 12UTC**, f006–f018, ROI5–23E/37–55N:13 files /9,549,846 bytes. Dataset `gfs_7e50d32a5e27e7b541844624`, valid27 October18UTC–28 October06UTC; finalized17:05:21UTC. Exact publication time remains unknown. Job `cb3ba363-6a32-47cd-96fe-42c3df874d62` completed; this was a network download, not the bundled fixture. The native decoder validated the NOAA metadata. The adapter enforces NOAA's documented ten-second wait after automated fetch attempts, including retries and adjacent crops; cancellation remains interruptible.

## Automated verification

Commands executed from the root with the installed locked environment:
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

Backend: **56 passed**, one upstream Starlette/httpx deprecation warning; lint/format passed34 Python files, mypy passed21 source files. Frontend lint, TypeScript and production build passed. Main application JS307.09kB (93.96kB gzip), lazy MapLibre chunk1,079.40kB (293.95kB gzip); its bundler size warning remains disclosed. No external tile/font service is loaded.

Failure regressions include invalid terrain/altitude/time, changed forecast metadata, finalized-cache corruption, missing files, overlap disagreement, exhausted segment/input quotas, cancellation, duplicate job claims, stale loaded source, damaged stored output, unavailable worker, retry restrictions, missing/unrelated backup database and antimeridian geometry. Runtime/source traceability and a passing computation do not supply flight calibration.

Browser final results and quiet-state backup verification are recorded below. The initial overlapping build/scientific/browser run had two timing failures (map readiness and UI result selection) while the scientific suite and build were active; results from that invocation are not represented as a pass. Verification is repeated against the completed build without competing scientific workloads.

## Remaining acceptance limits

No native Windows run, independent8GB-host test, full72h test, observed-flight error validation, pressure-plane contours or3D weather-volume display has been completed. No terrain/site survey or hardware measurements were supplied. Automatic disk eviction, SSE and numerical checkpoint continuation remain open. An80m initial altitude at the example site is correctly below coarse GFS terrain; a float-only study is not evidence that a ground launch can reach that state.

## Final browser and fresh-cycle saved workflow

The clean final invocation passed **all6 Chromium end-to-end tests in1.9minutes**: offline map/timeline/provenance with external HTTP blocked; mission edit/compute/export/refresh/archive reopen; explicit NOAA failure and estimate invalidation; mobile/keyboard access; actual cached NOAA vectors/vertical column/map probe; oversized-download rejection. The earlier two timeouts did not reproduce against the completed build with the competing suite finished. No application change or relaxed timeout was needed for the rerun.

A separate real12UTC-cycle float-only study, start18UTC,12500m,1h, was saved by the production worker in about3.2seconds. Result `189b5161-c01a-4ea7-aabb-1de6991b5951`: **56,248.460235m**,31 samples; output SHA256 `a5085396701176e5247454c329072e31873a704f6d9346337bccf63aa151633a`. Full evidence: [noaa-fresh12-simulation.json](examples/noaa-fresh12-simulation.json). JSON, CSV and2D GeoJSON exports returned200; GeoJSON is a Feature/LineString for this non-crossing route. Original editable mission assumptions were restored as a new immutable revision after queuing the study.

## Final offline replay and recovery evidence

The final normalized offline replay reproduced the saved API output **exactly**, including all1,441 sample records and output SHA256 `78b7a99d9556bb35db42643e3ccb0236152766518f921c3f1ce042b58654fb6b`. No HTTP acquisition was allowed. The final measured run took178.472s with211.438MiB peak RSS under the6GiB address-space cap. Resource metrics, exact procedure hash, source/dependency identity and segment IDs are retained in [long-forecast-review-results.json](long-forecast-review-results.json).

The first CLI replay had identical numerical values but a different serialized hash because direct mutable-model assignment retained integer12500 where the API normalized float12500.0. The procedure now validates the complete edited configuration through the same Pydantic schema before calculating/hashing. The final rerun confirms exact equality; no tolerance was used to conceal that difference.

Backup recovery caught a separate defect before handoff: SQLite's connection context manager commits but does not close, so temporary target WAL/SHM files entered a manifest and disappeared on later closure. Explicit connection closure/checkpointing now precedes file hashing. The regression verifies every manifest entry after the backup function returns and rejects transient-file entries. Both backup regressions passed after the fix.

Corrected quiet-state backup: `/workspace/stratos-backups/review-20261027-1728`, **311 retained files**. Every listed file exists and matches its SHA256; SQLite integrity_check returnedok. A disposable copy restored through the actual API reopened both real studies with their exact stored hashes. The earlier1724 backup is explicitly marked BACKUP_FAILED and retained as failure evidence. The live launcher was also stopped/restarted; both real studies reopened with unchanged hashes and worker healthready.

Screenshots inspected: [48h trajectory](screenshots/noaa-48h-review.png), [fresh-cycle trajectory](screenshots/noaa-fresh12-review.png), [actual weather explorer](screenshots/weather-explorer-review.png). The separate capture recorded no browser exceptions. Basemap geography is coarse; the manually supplied European labels are not a global navigation product.

Final backend rerun after the backup fix: **56 passed in68.12s**, lint/format/mypy passed. The strengthened independent GeographicLib arc reference also passed all4 solver-specific cases. A separate actual-GFS step refinement at60/30/15s gave endpoint differences versus15s of6.094mm and2.516mm respectively; this is numerical discretization, not forecast accuracy. Full values: [real-noaa-v2-convergence.json](real-noaa-v2-convergence.json).

Final local health check: API statusok, independent workerready, queueidle; root client and bundled geography returned200. One mission,11 saved studies and4 registered NOAA input datasets remain available. Cloud install/start instructions and the inspected `stratos` repository mount are saved in the configuration draft; this does not apply or publish the draft.
