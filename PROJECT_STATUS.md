# Project status

## Delivered: P0 foundation + extended P1 engineering slice

**P0 implemented and tested. P1 core weather-to-saved-trajectory workflow tested with actual NOAA inputs. Full P1 has remaining tasks below. P2–P7 not started.** No flight-readiness or hardware qualification is claimed.

Specification read in full before changes; repository verified empty. Pre-implementation audit: `ARCHITECTURE.md`. Decisions: `DECISIONS.md`. The original screenshot was not supplied; styling follows the written visual contract.

## Verified functionality

- [x] Modular Python/React monorepo, normalized typed mission configuration, round-trip YAML and immutable revisions.
- [x] SQLite WAL/FULL synchronous writes, Alembic migration, durable queue and separate single worker with OS lock.
- [x] Cancellation, explicit interrupted-job state, bounded queue/wall time/cache/arrays, verified weather-file reuse.
- [x] Entirely offline DEMO workflow with explicitly synthetic meteorology and GRIB fixtures.
- [x] Actual NOAA cycle discovery and cropped GRIB filtering/decoding/cache; no provider/cycle substitution.
- [x] Space/time/height interpolation, geometric/geopotential conversion, log-pressure recovery and invalid-volume rejection.
- [x] WGS84 RK4 L0 ascent/float/optional flat-plane descent with scientific reference/convergence tests.
- [x] Interactive offline MapLibre map, synchronized chart/inspector, mission editor, download estimates, archive and JSON/CSV/YAML exports.
- [x] Manifests retain exact configuration, weather URLs/checksums, output hashes, source hashes and runtime/package versions.
- [x] Saved JSON identical after real API/worker restart; fresh app instance and browser refresh/reopen also verified.
- [x] **91 backend tests passed**, Python lint/format/type checks passed, frontend lint/typecheck/build passed, **11 isolated browser tests passed**. Separate real-NOAA browser/map/reopen/mobile check passed.
- [x] Frozen install/migration script exercised; reusable installation/startup fields saved in cloud environment draft. Publication/fresh-task restoration remain separate actions, not claimed.

## Real input/output evidence

NOAA GFS **2026-10-27 06 UTC**, deterministic **0.25°**, leads **f006–f008** valid 12–14 UTC, ROI **5–20°E / 40–52°N**, **1,253,205 raw bytes**. Exact filter URLs, timestamps and hashes are retained with raw inputs. A separate 36,534-byte real crop supports fast offline decoder checks.

| Example in `docs/examples/` | Result | Output SHA-256 |
| --- | --- | --- |
| `noaa-simulation.json`: 12,500m float, 1h | 64,700.703589m, 31 samples | `cd352deeb9bd741a3c018eff2d0a6e5445665ef3112c2fae202528fee8953770` |
| `noaa-ascent-simulation.json`: assumed 150m start, 2m/s ascent to 12,500m, 0.2h float | 78,270.110094m / 6,895s, 60 samples | `0f28299072a4c9c3065a17767123f6210b1853b7edf02220339499def37508e8` |
| `synthetic-simulation.json`: constant U12/V3m/s, 80m start, 1.5m/s ascent, 6h float | 369,595.187473m / 29,880s, 250 samples | `dc886326c7f3a3db72c31704587ff2f3b6d2d31318ba2ab09ee4fedb1a352a3b` |

These three examples use the preserved schema1 solver. New schema2 studies use altitude-aware curvature and output-cadence-independent integration; old evidence is not reinterpreted.

Three real point checks match direct ecCodes extraction to numerical precision; the tiny crop also agrees through cfgrib/xarray. Both real tracks reproduce offline with `uv run --frozen python -m scripts.reproduce`, with exact hashes in this instance. Raw inputs: `tests/fixtures/noaa-gfs-20261027-06-regional/`. Results and tolerances: `docs/verification.md`.

The initial 80m launch altitude is **correctly rejected** below coarse GFS terrain at the example point. The real ascent uses an explicitly assumed 150m start, not surveyed elevation or demonstrated launch clearance.

## Remaining P1 tasks

- [x] Opt-in bounded adjacent crop/time-window acquisition, exact run identity, overlap checks, source precedence, quotas and a three-window LRU. Tested on a real 48h route with 16 segments. Missing weather and exhausted limits still fail explicitly.
- [x] Cached real-weather altitude/time map vectors and cursor pressure-level columns, with explicit invalid-volume errors.
- [x] Actual retained pressure-plane maps, wind-speed/temperature isolines with terrain/missing-data masks, cursor readout, native/display resolution labels and hashed slice export.
- [ ] A full3D weather-volume display remains unimplemented.
- [x] Real 48h float transport demonstrated and repeated: 4,596.334km, 1,441 saved samples, 16 weather segments, 46,715,809 verified raw bytes. Final exact offline replay peak RSS211.4MiB with a6GiB address-space cap.
- [ ] Full 72h demonstration remains unrun; Linux process caps do not qualify an independent 8GB host.
- [ ] Native Windows and an independent 8GB-host validation. Current Linux host has more RAM; resource bounds alone do not establish this gate.
- [x] Paginated archive/counts, atomic queue claims, exact-payload retries, worker heartbeat and restart-required detection, output integrity guards, consistent checksummed backup.
- [ ] Automatic disk-cache eviction, SSE progress and numerical checkpoint continuation remain deferred. Polling, manual cache management and verified input reuse are implemented.

New scientific/reliability review, current-cycle download and final verification: `docs/RESEARCH_REVIEW.md` and `docs/REVIEW_VERIFICATION.md`. Next single slice: `NEXT_CODEx_TASK.md`.

## Evidence classes / limitations

**Verified:** computational capabilities listed above, real input/output samples and screenshots. **Implemented but uncalibrated:** L0 transport and interpolation of model forecasts; no observed-flight skill or validated confidence corridor. **Research only:** L1/L2 envelope/thermal/leak calibration and mission-success probabilities. **External requirements:** measured power/RF/thermal behavior, compatible receivers, qualified hardware/envelope, terrain/site survey and aviation/radio permissions.

NOAA was initially denied by proxy policy; later discovery/download succeeded. Future new downloads depend on service/network availability. Existing real fixtures and cached simulations work offline. No hardware, radio, power, data-recovery, imaging or launch-readiness claim follows from P0/P1.

## Configuration / repository

Cloud draft saves official NOAA domains, tested installation and service startup/readiness instructions. Saving does not publish a snapshot or prove fresh-task restoration. Review/save and publication are product actions. The complete implementation is published on GitHub `main` at scientific-source commit `9d49d035dde0ac47cb8ff9c6bfa84e5f0a79e525`; final documentation/evidence is committed separately. Historical runs were created in an unborn repository and retain `git_commit=null` plus source hashes; the final three actual API/worker calculations retain the committed source identity. No public service or PR is implied by source publishing.

## Reliability review additions, 27 October 2026

Fresh NOAA **12UTC** cycle, f006–f018, was downloaded through the durable queue: **13 files / 9,549,846 bytes**, valid 18UTC–next-day 06UTC. NOAA's documented ten-second wait is enforced between automated filter fetches, including retries. Full raw inputs stay in the ignored local cache and backup; small offline fixtures remain in the repository.

The final API/worker 48h record is `db683209-a61d-4d0d-91c6-ccc5006bfadc`, output SHA-256 `78b7a99d9556bb35db42643e3ccb0236152766518f921c3f1ce042b58654fb6b`. `docs/examples/noaa-48h-simulation.json` retains its full configuration, results and manifests. This is an assumed constant-altitude transport study, not demonstrated balloon endurance or forecast skill.

Final review: offline schema2 replay exactly matched the saved 48h output hash and all1,441 samples after configuration normalization. A corrected311-file backup passed complete checksum/integrity verification and an isolated API restore of both NOAA studies; a live API/worker restart preserved them. Detailed metrics and the two defects caught by these checks are documented in `docs/REVIEW_VERIFICATION.md`.

The earlier cloud draft recorded an unborn checkout. Final onboarding updates replace that historical ref with the exact published local HEAD at mount path `stratos`, origin `MatteoSchiavi/stratos`. The empty sandbox protection directory `/workspace/.git` and the empty uv cache marker `.cache/uv/sdists-v9/.git` are not additional project checkouts. Installation, startup and official NOAA custom network domains remain preserved. Environment publication/fresh-task restoration are still not claimed.

## Second P1 revision

Pressure-level sampling now uses actual GFS height surfaces and masks underground levels; independent ecCodes checks and analytic contour topology tests cover the new path. Isolines use a bounded sampled grid with explicit interpolation limits. Inspections include loaded-code traceability; stale scientific API processes cannot publish new slices.

Saved metadata is cross-checked against the manifest as well as numeric output hashes. Backup verifies every required forecast source, refuses active snapshots and reconstructs missing redundant exports only from verified database evidence. Read-only verification and restore into a new directory are provided by `scripts.verify_backup`.

Forecast requests can select a window of at most72h within GFS hourly leads0–120, so a launch after initialization no longer loses that delay from its requested72h horizon. Download jobs have a30min cap and show NOAA pacing as a lower bound. A later f078/f079 decoder test uses explicitly synthetic GRIB records; a full real72h study is still unrun.

UI request fingerprints preserve the connection between estimates and inputs; late saves preserve newer edits, and stale inspections cannot repopulate a changed dataset. Findings, commands, exact results and remaining limits are in `docs/P1_SECOND_REVIEW.md`.

Saved-study comparison now aligns real saved paths in elapsed/UTC time, exposes changed inputs and source identities, and exports hashed scenario-sensitivity data. Two exact NOAA cycle windows are bundled for a controlled common-valid-time comparison. Browser tests use a separate server/temp database; continuous mission fields no longer fail native step validation. Full user instructions are in `INSTALL_AND_USE.md`.

## Published-source release verification

- Scientific-source commit `9d49d035dde0ac47cb8ff9c6bfa84e5f0a79e525` was pushed to GitHub main and independently cloned over HTTPS into a path containing spaces. `bash scripts/install.sh` completed with fresh locked dependencies, native ecCodes2.50.0, frontend production build and migrated database. The clean instance imported three dated real NOAA references, calculated a one-hour study and exactly matched all31 samples/output hash from the planning instance. This is a fresh installation on the same Linux host, not an independent-machine qualification. Evidence: `docs/CLEAN_INSTALL_VERIFICATION.json`.
- Committed-source API/worker replay of the48h study exactly matched all1,441 previous snapshots and output hash `78b7a99d9556bb35db42643e3ccb0236152766518f921c3f1ce042b58654fb6b`. New result `5a98be5a-45ab-4db5-bd2c-a2db5665d646` retains the actual commit identity.
- Controlled06UTC/12UTC real GFS studies start at the same18UTC time and12,500m height for1h. Their distances are58,132.788354m and56,248.460235m; endpoint separation is1,952.742670m. Only the weather dataset differs. This is forecast-cycle sensitivity, not an accuracy/confidence measurement. Full manifests and hashed comparison are in `docs/examples/noaa-cross-cycle-*.json`; summary: `docs/P1_SECOND_REVIEW_RESULTS.json`.
- Final quiet-state backup `/workspace/stratos-backups/final-20261027-2324`:327 files,15 simulations and21 referenced weather sources verified. Restore into a new directory reopened the three final NOAA results with exact hashes; original backup reverified unchanged. Evidence: `docs/BACKUP_RESTORE_VERIFICATION.json`. The runtime cache/database/backup are local and ignored by Git; portable small NOAA fixtures are committed.
- Actual Chromium screenshots of the comparison and pressure-surface explorer are retained in `docs/screenshots/`. Final local suites:91 backend tests and11 isolated browser scenarios. GitHub Actions status could not be read because the cloud policy denies `api.github.com`; remote CI success is not claimed.

Full installation, configuration, UTC planning, NOAA acquisition, comparison, export, backup and restore instructions: `INSTALL_AND_USE.md`. P1 remaining gates above remain open; no later phase has been declared complete.
