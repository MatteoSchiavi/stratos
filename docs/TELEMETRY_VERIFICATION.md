# Telemetry and recovery verification — 28 October2026

## Scope

All seven requested capabilities are implemented as local engineering tools. Packet/archive correctness and software workflows are verified. Radio delivery, entered contacts, power parameters and geographical permission profiles remain explicit assumptions/evidence inputs. No transmitter, measured RF calibration, flight readiness or full later-phase completion is claimed.

## Reproducible checks

```sh
.venv/bin/ruff check packages services scripts tests
.venv/bin/ruff format --check packages services scripts tests
.venv/bin/mypy packages services --explicit-package-bases
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.reproduce
.venv/bin/python -m scripts.reproduce_telemetry --output /absolute/new/evidence-directory
.venv/bin/python -m scripts.reproduce_telemetry --long --output /absolute/new/stress-directory
cd apps/web
npm run lint
npm run build
STRATOS_CHROMIUM=/usr/bin/chromium npm run test:e2e
```

Final backend: **123 tests passed in32.73s**, including32 telemetry cases. Python lint/format passed53 files and mypy passed33 source files. One upstream Starlette/httpx deprecation remains. Frontend lint/types/production build passed; the main client is about354kB and the pre-existing lazy MapLibre chunk remains about1.08MB with the disclosed bundler warning. The final browser run and committed-source/API evidence are appended below.

Independent checks include hand-assembled fixed packet bytes, corruption at every single bit of CRC-protected packet families, global coordinate quantization bounds, sequence wrap/invalid sentinels/noncanonical varints, four Semtech symbol-time numerical vectors, different EU/US DR tables, FOpts/dwell limits, lossless float/epoch/order recovery, decompression bounds/corruption, extrema/path/clock discontinuities, short contacts between ticks, stale-fix timestamps, region/permission/outage/power gates, rolling channel occupancy, no reception oracle, protected tracking airtime and saved-evidence backup/restore/corruption guards.

Both original actual NOAA float/ascent examples still reproduce with exact output hashes and zero coordinate error in this instance. Their weather remains the dated27 October2026 GFS reference; no new live-weather claim is made.

## Verification-driven correction

An initial synthetic72h scheduling stress case generated4320 records, with a24h initial contact outage and a30s/24h fairness budget. Historical traffic consumed the budget early, leaving a maximum known-position age of82810.169s. This exposed a real scheduling-policy weakness.

The corrected scheduler reserves fresh airtime using the union of upcoming compatible time windows, accounts already-spent airtime and paces infeasible tracking cadences. Under the same explicitly synthetic assumptions/seed, maximum known-position age fell to1520.082s (~25.3min), with final age300s. Full-record recovery changed736→615 while received-position count changed146→487: this is an explicit freshness/history tradeoff, not an across-the-board delivery improvement. Total modeled airtime59.616s over the two contact days stayed inside rolling budgets. The32nd telemetry regression protects against short-study starvation as well.

The corrected synthetic72h computation took26.17s, with126344KiB peak RSS (~123.4MiB) on this Linux machine while other checks ran. Energy balance residual was about-2.8e-10J. This is not a real72h NOAA trajectory, an independent8GB host, native Windows qualification or measured electrical behavior. Exact source/output manifests and a committed-source repeat are retained with the release evidence.

## Known limitations

- Region support is a pinned RP002-1.0.3 planning subset. Current national/airborne authorization, EIRP, actual hardware channel plans and full regulatory qualification are separate.
- Contact windows/compatibility and independent loss probabilities are supplied inputs. No gateway-position coverage claim, terrain/RF-margin model or observed decode is fabricated.
- EMERGENCY has no application CRC and relies on externally verified LoRaWAN MIC; its time/sequence quantization and out-of-band epoch/session requirement are explicit.
- Freshness/history allocation is a conservative bounded heuristic. Correlated losses, acknowledgments/rejoin traffic and globally optimal scheduling are not modeled.
- Lumped power lacks measured cold/ESR/transient/solar calibration. Local archives are checksummed artifacts, not a qualified on-device flash journal or incomplete-prefix salvage.
- Native Windows, independent8GB and the remaining real-weather/3D P1 gates remain open.


## Final committed-source workflow

Scientific implementation `2523bd5134f2988ed001aa08654c09eb445784f1` was pushed to GitHub main. The final full suite passed **123 backend tests in32.73s and14 isolated Chromium scenarios in1.1min**. A final frontend-only refinement reopens a saved study using its original inputs when there is no current draft, and labels reopened archives accurately; frontend lint/types/build plus all three telemetry browser workflows passed again in15.0s after that change. No scientific implementation changed after the123-test run.

The actual restarted API/worker then computed and saved:

| Study | Saved ID | Modeled result |
| --- | --- | --- |
| Explicitly synthetic one-hour contact scenario |`392161f3-f141-4d39-8145-65571e17f533`|53/60 unique records;8.082432s airtime;2.132365J radio energy|
| Retained real NOAA modeled trajectory with explicitly synthetic contacts/loss/power |`4d11bef1-e2b3-4d0b-8c14-40030e6e2bf2`|51/60 unique records;25 known positions;8.952832s airtime;2.262925J radio energy|

The NOAA source is the immutable27 October2026 12UTC-cycle study `d2fbed7e-a0e7-48ce-bfb7-63bd8a34a4f9`, output SHA `f94d5b9a95f539c33b444a05d4a3f9246b2162c1274e67b0d66f8b7719072d6f`. Its source sample cadence is120s while the recovery log cadence is60s; intervening entries correctly mark the unavailable contemporaneous fix invalid rather than inventing new measured positions. Full configurations, flags, outcomes, hashes and startup code identity are in `examples/telemetry-*-study.json`.

Archive `1dadd4ab-efb5-4669-830c-087870a94193` retained all31 original NOAA-derived typed observations in1700B. Its actual binary download was posted back to the real decoder, which reproduced every original observation and the explicit18UTC epoch exactly. Evidence: `TELEMETRY_API_VERIFICATION.json`, `examples/telemetry-noaa-archive.json` and `examples/telemetry-noaa-observations.stla`.

A quiet-state backup at `/workspace/stratos-backups/telemetry-release-20261028` verified327 files,15 original simulations and21 referenced forecast sources. A separate restore reopened both new telemetry studies and the new archive with identical complete evidence/binary; the original archive remained unchanged and verified. The telemetry records are transactionally retained in SQLite and included in its integrity checks; runtime state is ignored by Git. Details: `TELEMETRY_BACKUP_VERIFICATION.json`.

The committed-source synthetic72h repeat exactly matched output SHA `eadd421deab6d230689a9bffa537949ac7d63e74b27f1afb9ef63da5d76638b8`. It ran in22.96s with125728KiB peak RSS (~122.8MiB) in a less contended repeat. Exact metrics/source identities: `examples/telemetry-72h-stress-verification.json`. The earlier stress-policy comparison is preserved in `TELEMETRY_SCHEDULER_REVIEW.json`; it is historical software evidence, not an independently calibrated radio comparison. Protocol vectors: `examples/telemetry-wire-vectors.json`.

Actual desktop/mobile, US915 rejection and archive screens are retained in `screenshots/telemetry-*.png`. GitHub source push is verified independently from local checks; remote Actions success is not claimed under the current API destination policy.
