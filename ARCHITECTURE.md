# STRATOS architecture and specification audit

Audit baseline: specification v2.0, read in full; empty repository (unborn `work` branch), Python 3.12.14 / Node 24.19.0. User authorization covers implementing P0/P1; instructions in the supplied specification are design requirements within that scope, not authorization to transmit, launch, publish, or implement P2–P7.

## Proposed vertical slice

React/TypeScript/Vite → same-origin FastAPI → versioned mission revisions and durable jobs in SQLite WAL → one separate worker → bounded NOAA GRIB cache → pressure-column sampler → WGS84 kinematic integrator → immutable result + SHA-256 manifest → interactive MapLibre map and synchronized chart. Everything except downloading a new forecast works without Internet. No Redis, cloud account, telemetry receiver, hardware, or paid service.

Python packages under `packages/` separate configuration, meteorology, and flight numerics from HTTP and persistence under `services/api/`. Alembic owns schema changes. One worker at a time uses SQLite job claims; interrupted jobs become explicitly interrupted, never silently completed. Cache writes use temporary files and atomic rename. The web client submits jobs and polls persisted status. It never computes scientific results.

## Audit findings before implementation

| Area | Evidence / limitation | Decision |
| --- | --- | --- |
| Repository | No source, dependency declarations, commits, or branches on origin | Establish a minimal monorepo; no existing behavior to preserve |
| Dependencies | FastAPI 0.141.1, Pydantic 2.13.4 and NumPy 2.3.5 installed; cfgrib/ecCodes, SQLAlchemy/Alembic absent. npm metadata reports React 19.3.1, Vite 8.3.5, MapLibre 6.16.0; installed Node meets declared engines | Install in isolated `.venv`, pin resolutions in lockfiles; verify imports and browser APIs |
| NOAA | NOMADS requests return proxy CONNECT 403; no credential is required by the public service | Official domains saved; later runtime access succeeded and a 2026-10-27 06 UTC cycle was downloaded and tested (see verification report) |
| Forecast horizon | 384h is a product horizon, not a promise of hourly files or current availability | P1 requests hourly leads only within first 72h; verify selected files exist; no silent cycle fallback |
| Run vs publication | Initialization time is not publication time. NOMADS is a rolling archive, not a forecast-at-time archive | Record retrieval time and run identity; no claim of historical forecast verification in P1 |
| Altitude | Isobaric surfaces move. Geopotential metres are not geometric MSL metres; pressure alone does not specify altitude | Interpolate actual HGT columns, convert height explicitly, interpolate pressure logarithmically; no standard-atmosphere replacement for missing GFS levels |
| Flight fidelity | A prescribed float altitude does not establish attainable lift, envelope survival, or payload endurance | Label every track L0 / uncalibrated; mass is recorded metadata and does not alter L0 advection |
| Geographic edges | Dateline, pole singularity, terrain and missing values can invalidate integration | Normalize longitudes, altitude-aware WGS84 differential transport, dateline-split exports and explicit domain errors; no latitude wrapping or weather extrapolation |
| Ground | User-supplied ground elevation is not a digital terrain model | GFS coarse surface height is a weather boundary only; descent landing is a configured flat-plane assumption, never a recovery prediction |
| Weather ROI | Unbounded moving tiles can cause unpredictable downloads and memory | Initial slice used a fixed crop. ADR-009 now adds opt-in bounded same-cycle adjacent/time segments, overlap checks and quotas; exhaustion or missing weather stops the job |
| Resource budget | Specification's 48–72h is reasonable only for cropped fields | One worker; 72h maximum, per-file and total cache caps, estimate shown before download, array memory guard |
| UI modes | Four modes do not include prospective planning | Keep mission mode DEMO for simulated records; independently label wind source `synthetic` or `NOAA forecast`. Reject unsupported hardware/live modes in P1; do not disguise forecasts as measurements |
| Offline maps | Public tiles are online dependencies with provider terms, rate limits and privacy implications | Bundle public-domain Natural Earth coarse basemap; no tile service or paid key. It cannot supply terrain or street navigation |
| Reproducibility | A code commit is unavailable before the first commit; raw package versions alone do not identify dirty code | Hash source tree as well as available commit, mission revision, weather files and outputs; retain inputs |
| Security | Local-first is not authentication; arbitrary remote writes and large imports are unsafe | Loopback default, same-origin writes, strict size bounds, no arbitrary upstream URL or file-path input |
| Missing requirements | No supplied screenshot, qualified envelope, site survey, measured loads, RF configuration, terrain product, or launch permissions | Use documented visual tokens; do not invent engineering evidence |

## Evidence classes

* **Verified:** only behavior covered by recorded test commands in `PROJECT_STATUS.md` and `docs/verification.md`.
* **Implementable but uncalibrated:** L0 transport, pressure-column interpolation, prescribed ascent/float/descent. Forecast data remain model output.
* **Research only:** buoyancy/leak/thermal envelope calibration, probabilistic flight success, multiweek trajectory accuracy.
* **External blockers:** future NOAA availability/network access for new downloads; bench hardware qualification and aviation/radio authorization. Software tests cannot remove the latter.

## Deliberate boundaries

P2–P7 have no placeholder endpoints or invented metrics. Connectivity, recovered bytes, solar power, images, approvals and readiness scores are not computed by P0/P1. A successful trajectory is evidence of a computational workflow, not flight readiness. Remaining P1 gaps must be recorded explicitly before calling that phase complete.

## Follow-up architecture review

The initial audit above records the starting assumptions. ADR-008–011 and `docs/RESEARCH_REVIEW.md` document the implemented refinement: versioned height-aware numerics, bounded weather windows, source-stable expansion, worker loaded-code identity, backup and actual cached weather inspection. `docs/REVIEW_VERIFICATION.md` records subsequent evidence.
