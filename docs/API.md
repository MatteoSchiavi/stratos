# P0/P1 API

`/openapi.json` is the authoritative typed schema. UTC offsets are required. Writes are local/same-origin with a 64KiB request limit. Errors retain field or job failure detail; later-phase modules have no fabricated endpoints.

| Route | Behavior |
| --- | --- |
| GET `/api/health` | Database query and independent worker heartbeat: ready, unavailable or restart_required |
| GET `/api/summary` | Saved record counts without loading full trajectories |
| GET `/api/providers/weather` | Implemented sources and evidence classes |
| GET/POST `/api/missions` | Latest mission summaries / normalized new immutable revision |
| GET `/api/missions/{id}` | Current mission pointer |
| POST `/api/missions/{id}/revisions` | New immutable config with same mission UUID |
| GET `/api/revisions/{id}` or `/yaml` | Exact configuration / round-trip YAML |
| POST `/api/missions/import-yaml` | Safe YAML and schema validation |
| GET `/api/weather/runs` | Published NOAA cycles and observed file leads; 502 on upstream failure |
| POST `/api/weather/estimate` | Packed/decoded byte estimates and resource bounds, no download |
| POST `/api/weather/downloads` | 202 durable cropped download job |
| GET `/api/weather/downloads/{id}` | Download job state |
| GET `/api/weather/datasets` | Finalized cached manifests |
| POST `/api/weather/explore` | Actual altitude/pressure-plane vectors, bounded scalar contours, selected state and vertical column |
| GET `/api/jobs` or `/{id}` | Persistent progress, error and result ID |
| POST `/api/jobs/{id}/cancel` | Cancel queued/running job |
| POST `/api/jobs/{id}/retry` | New job with original payload for failed/cancelled/interrupted jobs; 409 for completed |
| POST `/api/simulations` | Immutable revision UUID and optional expansion policy → 202 calculation job |
| GET `/api/simulations?limit=25&offset=0` | Newest-first summaries; limit 1–100 |
| GET `/api/simulations/{id}` | Complete record after configuration/output/manifest hash verification |
| POST `/api/simulations/{job_id}/cancel` | Job-cancellation alias; accepts a job UUID |
| GET `/api/simulations/{id}/trajectory` | Dateline-safe GeoJSON, two-dimensional WGS84 coordinates |
| GET `/api/simulations/{id}/export?format=json` | Full JSON; also `csv` and `geojson` |

Example calculation body:
```json
{"revision_id":"<UUID>","expansion":{"max_tiles":16,"max_download_mib":128}}
```
Expansion is optional, per-run and valid only for schema2 NOAA studies. Limits are 1–16 total segments and 1–128MiB verified raw inputs, including cache hits. Acquisition keeps exact cycle/member/grid, validates overlap and uses bounded time windows. Quota or unavailable data fails explicitly. No expansion policy means no adjacent network acquisition. The whole prescribed profile (maximum72h) must fit the selected initial dataset's valid-time horizon. Preflight rejects invalid initial weather and look-ahead initialization.

Explorer fields are `dataset_id`, aware `time_utc`, coordinates and vector `grid_size` (3–13). `plane` defaults to `geometric_altitude`, using `geometric_msl_m`. With `plane="isobaric"`, `pressure_pa` must identify an actually retained level. Omit pressure in altitude mode. `contour_variable` is `wind_speed` or `temperature`; `contour_grid_size` is17,25(default) or33. Responses include source/time/plane, masks, units, scalar values/levels, native/display resolution, contours, endpoint points, startup scientific-code identity and `inspection_sha256`. Missing cells break contours. No standard-atmosphere height is substituted. This endpoint never downloads weather or extrapolates. At most two bounding files are decoded per slice and a two-slice cache is retained. Pressure-level column entries and invalid-vector counts remain explicit.

Poll until `completed`, `failed`, `cancelled` or `interrupted`. Only completed jobs publish results. The queue holds at most eight active jobs. Loaded scientific code/dependency changes require restarting; a job cannot publish a result attributed to different loaded code. Numeric checkpoints and SSE are deferred. Checksum conflicts return errors rather than repairing provenance silently.

NOAA cache IDs are `gfs_<hash>`, not UUIDs. Exact input hashes, URLs and retrieval times are retained. GeoJSON omits a Z coordinate because geometric MSL height is not WGS84 ellipsoidal height; physical altitude remains in JSON/CSV and GeoJSON properties. Crossing tracks become MultiLineString.

Mission schema2 selects the height-aware solver; schema1 selects preserved legacy numerics. Mode DEMO means a simulated mission, independently of SYNTHETIC or NOAA_GFS wind source. All output samples are `modeled_uncalibrated`; hardware/live modes are rejected in P1.


Downloads support consecutive hourly leads0–120 with a maximum72h window (73 files); the mission profile cap remains72h. `/api/weather/estimate` includes `minimum_filter_wait_seconds` (pacing lower bound, excluding network/decode/retries). Provider capabilities advertise `max_lead_hours=120`, `max_window_hours=72` and actual adapter pressure levels. Job budgets are30min for download,15min for expanding studies and2min for cached studies.

Saved-record reads/exports return409 for inconsistent metadata/IDs as well as checksum damage. Scientific weather inspection returns422 if loaded code/dependencies changed; restart both services. Inspection is read-only and never downloads data.


POST `/api/simulations/compare` accepts distinct `reference_id`/`candidate_id` UUIDs, `alignment="elapsed"|"utc"` and `sample_count`3–1001 (default241). Both stored records pass full integrity checks before analysis. The response includes aligned/interpolated source positions, shared horizon, sampled separation/height metrics, configuration differences, source/cycle/solver identities, original output hashes, loaded-code identity and `comparison_sha256`. A missing UTC overlap returns422; damaged source evidence returns409. Comparison is read-only and performs no weather download or simulation. Values describe scenario sensitivity between predictions, not measured errors.
