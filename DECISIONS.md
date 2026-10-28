# Architecture decisions

## ADR-001 — Local modular monolith (accepted)
**Context:** one launch, modest laptop, no service budget. **Decision:** FastAPI, SQLite WAL/Alembic, separate single worker, React/Vite. **Consequence:** bounded concurrency; no distributed-queue complexity. **Evidence:** implementation verification tracked in `PROJECT_STATUS.md`.

## ADR-002 — Explicit L0 fidelity (accepted, uncalibrated)
Prescribed vertical profile and wind advection on WGS84; fixed-step fourth-order integration. No simulated lift, radius, energy, reception probability or calibrated uncertainty. Store these omissions as limitations rather than zero-valued physics. Hardware-dependent L1/L2 are research only.

## ADR-003 — Honest weather provenance (accepted)
Synthetic fixtures and downloaded NOAA runs have distinct providers and hashes. No fallback between them. Initialization, hourly leads, ROI, pressure levels, retrieval timestamp, request URLs, decoder/library versions and raw checksums are retained. Forecast-issued-at-time historical validation is deferred to P2. Official NOAA domains were initially blocked; subsequent runtime access and the 2026-10-27 06 UTC cycle were verified.

## ADR-004 — Geometric/geopotential height (accepted)
Use `H = R*z/(R+z)` and inverse with standard geopotential reference radius 6,356,766m. This is the disclosed standard-gravity approximation, not an exact geoid or latitude-dependent gravity model. Interpolate wind and temperature along the GFS height column, pressure in log space. Reject out-of-volume sampling and invalid cells.

## ADR-005 — Offline basemap (accepted)
Bundle coarse Natural Earth public-domain geography with attribution. MapLibre loads no external tiles/fonts. Offline route inspection is required; terrain and street resolution are unavailable. Screenshot image was not supplied; the design follows the specification's tokens and hierarchy.

## ADR-006 — Durable results and bounded jobs (accepted)
Persist job state, mission revisions and immutable simulation results; use temporary-file/atomic-rename caches. On worker interruption, mark running jobs interrupted and allow explicit resubmission, reusing verified weather cache entries. Automatic numerical checkpoint continuation is not claimed.

## ADR-007 — Phase and evidence gates (accepted)
Only P0/P1 are authorized for this milestone. Later modules remain deferred; hardware calibration and legal permissions remain external requirements. Completion requires tests, real data evidence, exact saved/reopened results and browser verification; any missing acceptance check remains open.

## ADR-008 — Versioned altitude-aware solver (accepted, uncalibrated)
Schema2 integrates WGS84 meridional/prime-vertical curvature plus prescribed height, with RK4 quadrature for horizontal air distance and numerical-step accumulation for ground track. Snapshot frequency does not define the numerical mesh. Schema1 preserves earlier reference-surface output hashes; it is never silently reinterpreted as the new solver. Geometric MSL height is an explicit approximation to ellipsoidal height until a site/geoid model exists.

## ADR-009 — Bounded weather windows and crop acquisition (accepted)
Decode two bounding hourly files instead of all forecast leads; retain at most three scientific windows. Optional adjacent acquisition stays on the same exact initialization/member/grid, compares overlapping fields within disclosed packing tolerances and stops on source/altitude/time/budget mismatch. Source precedence is independent of LRU recency. No extrapolation, silent newer cycle or fabricated weather. NOAA's documented ten-second fetch interval replaces the initial inadequate half-second pause.

## ADR-010 — Loaded-code identity and recoverable evidence (accepted)
Pin worker startup scientific-source/dependency identity and check it at calculation boundaries. A changed scientific source requires restarting, while UI-only edits do not change the model. A worker heartbeat is separate from database health. Hash-check saved results before export, retry original durable payloads explicitly and use SQLite's backup API plus checksummed raw inputs. Runtime/source checks are engineering traceability, not hardware or legal certification.

## ADR-011 — Offline real-weather inspection (accepted)
Import the permitted regional NOAA reference on first startup without Internet. Keep its original cycle/time/source labels. A bounded read-only slice cache supplies actual vectors and vertical columns; invalid probes keep a clearly labelled last-valid view. MapLibre is lazy-loaded and uses local assets. Archived results and edited mission inputs remain visibly distinct.

Recovery verification clarified ADR-010: close/checkpoint SQLite target connections before building a backup manifest. Commit-only context managers can leave transient WAL/SHM entries that disappear later. The backup regression now verifies every listed file after return, and a real isolated restore passed.

## ADR-012 — Actual pressure planes and bounded contours (accepted)
A pressure plane samples one retained GFS isobaric level directly, interpolating horizontally/in time and using that surface's actual HGT. Surface pressure/height mask underground levels. The separate geometric-altitude sampler and legacy replay remain intact. Marching squares uses an asymptotic saddle decider, terminates exact critical crossings and breaks at missing cells; a17/25/33 sample display grid and native0.25° source resolution are labelled separately. Curves are display interpolation, not observations or added forecast resolution.

## ADR-013 — Cross-record identity and recoverable archives (accepted)
Reopening/export checks IDs, mission labels, mode, source and timestamps against immutable manifests, alongside numeric/config hashes. Backup verifies pinned raw forecasts from the actual database snapshot and rejects queued/running snapshots. A verified database can reconstruct a missing/damaged redundant JSON export; it cannot invent missing raw weather. Read-only archive verification and restore into a new directory refuse overwrite/corruption and preserve failed evidence.

## ADR-014 — Separate absolute forecast lead from window length (accepted)
GFS hourly products extend through lead120. P1 accepts a cropped window of at most72h within those leads, rather than confusing lead72 with a72h future profile. Resource caps remain in force. Up to73 files require at least720s of inter-request pacing; download allowance is30min, expanding studies15min and cached studies2min. Availability is verified, never assumed from a directory or initialization time.

## ADR-015 — Preserve request and edit identity (accepted)
Estimates carry their original input fingerprint; a late response cannot certify changed settings. Inspection responses carry sequence tokens and exact plane/source labels. Revision-save completion clears only the draft actually saved, preserving later edits. Browser regression tests delay genuine backend responses rather than substituting simulated scientific results.

## ADR-016 — Saved-study sensitivity with explicit time alignment (accepted)
Compare immutable predictions over a shared interval using either equal elapsed time or equal UTC. Interpolate saved positions along shortest WGS84 geodesics and heights linearly; report sampled horizontal/height differences and exact changed configuration fields. Retain source IDs, cycle/solver identities, source/output hashes and a comparison content hash. No new integration, observations, forecast-error claims or calibrated confidence region is introduced.

## ADR-017 — Offline controlled-cycle evidence (accepted)
Retain a small exact hourly window from each of two previously downloaded NOAA cycles at the same valid time. Preserve original bytes/URLs/retrieval metadata and parent provenance. Register these explicitly dated inputs offline, without treating them as current weather. This makes a fresh installation's real-data comparison reproducible under a blocked network policy.

## ADR-018 — Continuous inputs and isolated verification (accepted)
Browser stepping is a UI constraint, not a scientific quantization rule. Continuous mission values use arbitrary numeric precision; integer controls remain discrete. The browser regression suite owns a separate server/worker and temporary database, so verification cannot modify launch planning state. The portable installer resolves its own checkout and defaults to the tested Python3.12 environment.


## ADR-019 — Explicitly requested telemetry slice (accepted, 28 October2026)
The user's new request authorizes this bounded P3/P4-related module after the earlier P0/P1 milestone. It does not override evidence gates or declare intervening/full later phases complete. Preserve the working weather/trajectory tools; hardware/network integration and calibration remain separate.

## ADR-020 — Versioned wire contract and regional uplinks (accepted)
Define global24-bit coordinates, explicit mission-relative epoch/time/sequence/validity, fixed-point fields, independent packet delta state and strict corruption/range validation. NAV/NAV+ENV/HISTORY have application CRC16;11B EMERGENCY trades fields/application CRC for US915 DR0 compatibility and requires external verified LoRaWAN MIC. Pin RP002-1.0.3 regional DR/BW/payload tables rather than assuming EU and US share settings. Model FOpts/PHY overhead, conservative US dwell/channel windows and EU shared-sub-band duty. This is no airborne authorization or complete regulatory certification.

## ADR-021 — Lossless originals and independent lossy summaries (accepted)
Archive original typed observations before radio quantization using resettable prefix deltas and bounded checksummed compression blocks, plus checked epoch context. Scientific summaries retain selected extrema/validity/clock/path events and are separate exports. A failed/bounded summary never discards a verified original archive. Truncated archives fail validation; flash-journal/power-cut salvage remains unqualified.

## ADR-022 — No reception oracle and protected fresh airtime (accepted)
A durable event scheduler intersects entered contacts, region permissions, supported channels, outages and finite energy. Sender fixed repeats/retirement never depend on seeded receiver outcomes. Receiver deduplication is separate. Stress verification found historical data starving later tracking; reserve fresh airtime against upcoming compatible time windows and pace infeasible cadences before spending the remainder on history. This conservative heuristic trades complete-record recovery against position freshness, without claiming global optimality or calibrated probabilities.

## ADR-023 — Task-focused interface and immutable source identity (accepted)
Separate packet checking, recovery planning and archives; separate cached weather inspection from acquisition. Remove deferred navigation, scope trajectory actions to their workspace, preserve telemetry edits across navigation, collapse completed inputs, and disclose advanced probe/configuration controls. Pin selected trajectory ID/output hash/epoch; reject edited data misrepresented as its original source. Delayed analyses retain original-input fingerprints and visibly become stale after edits.
