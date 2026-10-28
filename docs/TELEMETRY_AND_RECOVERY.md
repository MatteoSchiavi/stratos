# Telemetry and recovery tools

The new module is an explicitly requested engineering slice: it does not declare P2–P7 complete. The packet codec and archive are executable tools. Contact delivery, power and scheduling are **simulated from supplied assumptions/evidence**, not measured radio performance.

## A shorter workflow

Open **Telemetry** in the main navigation. The global trajectory-run button is shown only in its relevant workspace. Navigation no longer advertises unimplemented Test/Flight pages. Telemetry inputs survive switching workspaces; a saved recovery link reopens its immutable result. Completed results collapse settings, with exact-input loading available explicitly.

1. **Packet & airtime:** choose NAV, NAV+ENV, HISTORY or EMERGENCY; choose EU868 or US915 and an actual regional DR/SF/BW. Encode & validate returns real binary hex, decoded values, application limit, PHY size, overhead and calculated airtime. HISTORY uses the first eight current observations; other families use one. Edit or import observations in the full configuration. Inspect CRC/MIC limitations before firmware integration.
2. **Recovery planner:** set UTC epoch, study duration, logging cadence, tracking cadence and history group size. Enter receiver identities/contact windows and loss assumptions, or import a full configuration. Calculate recovery uses the durable, cancellable worker. Review unique recovered records, unrecovered data, position age, sender backlog, actual chosen packet hex, airtime, energy and blocked decisions. Export the full immutable study/configuration and reopen it later.
3. **Archive & summaries:** archive current input observations or an entire saved trajectory. It writes a lossless delta archive, verifies round-trip equality and separately generates a lossy scientific summary. Download `.stla` and summary JSON separately. Import `.stla` to verify/decode original records plus their epoch context. Saved archives can be reopened from the archive list.

For weather, **Simulate → Weather inputs** now opens **Explore cached weather**. **Acquire new forecast** contains discovery, estimates and download controls. Probe coordinates/display-grid controls are disclosed separately; click the map to inspect another point.

## Inputs and provenance

The initial configuration is a clearly labelled one-hour synthetic example: fictitious receiver windows, test geofence/permission reference and assumed power/loss values. It makes the tools reproducible offline; it is not coverage evidence. `GET /api/telemetry/example` exports the exact example.

Use **Use a saved trajectory as the position source** to transfer an immutable modeled path and its UTC epoch. Review the resulting horizon and explicitly enter receiver windows/geographic profiles that actually apply. Receiver windows are not automatically inferred from a gateway's coordinates. Model samples remain simulated even if their weather input came from NOAA.

**Input data & full configuration** provides JSON export/import/validation. Imports can carry:

- `positions`: chronological typed observations, mission-relative seconds, explicit clock/fix validity and `measured|simulated|assumed` origin. Decoder output does not automatically establish measured provenance.
- `contacts`: start/end seconds, stable receiver ID, EU868/US915, supported uplink DRs, optional supported-frequency mask, compatibility declaration, source, `assumed|predicted|observed` evidence class and loss probability. Null frequency mask declares the whole supported plan; this is a user assertion requiring receiver verification. Imported observed evidence is not independently authenticated by this module.
- `outages`: arbitrary blocked communication intervals, independent of nominal contact windows.
- `profiles`: explicit geographic rectangles (dateline crossing supported), validity intervals, pinned radio region, permission flag/reference, conservative duty fraction and optional stricter dwell limit. Unknown/stale positions, ambiguous overlapping profiles and missing permission block transmissions. Configured rectangles do not create authoritative borders or legal authorization.
- `power`: initial/capacity/reserve battery joules; capacitor F and initial/max/wake/sleep voltages; constant assumed harvest/idle/TX W; RX allowance J; charging W/efficiency. Units are explicit. No measured cold/ESR/load transient or solar model is implied.
- `fresh_interval_s`, `fresh_airtime_fraction` (default0.8 when a fairness budget is enabled), `history_batch`, `history_repeats`, `max_fix_age_s`, `seed`, optional independent `fair_use_s_per_24h`, FOpts and bounded study scheduling step.

JSON telemetry study/archive configuration requests are capped at2MiB and5000 observations; other ordinary application writes retain64KiB. Binary archive imports are capped at4MiB. Scheduling is capped at30000 regular ticks/40000 total event instants and5000 transmitted packets, with the existing2min worker budget and cancellation. Source trajectories are validated through their saved hashes before conversion.

## Scheduling behavior

The event set includes regular ticks, sampling instants, retained fixes and contact/outage/profile boundaries. Full packet airtime must fit compatible windows, the region permission interval and the outage-free interval. Supported channel masks/hopping and regional airtime restrictions are checked. No duty allowance is multiplied by gateway count or EU channel count.

Fresh tracking takes priority; the scheduler chooses the richest feasible NAV+ENV, NAV or EMERGENCY family (emergency first when battery headroom is critically low). US DR0 therefore falls back to11B EMERGENCY rather than sending an illegal19/24B application packet. Historical groups shrink until actual encoded size/contact/energy fits. Scalar extrema, recent path changes and oldest-time tie breaks prioritize local historical records. This is a bounded greedy policy, not a globally optimal mission-success solution.

Stored fixes are not re-timestamped as newly measured. A new log entry without a contemporaneous fix marks that position invalid; fresh transmissions may select the newest still-eligible earlier fix with its original timestamp. Receiver freshness metrics use decoded emergency-minute quantization and distinguish “never received” from a known old position.

A sender cannot know whether an unconfirmed uplink decoded. Fixed repeat/retirement decisions depend only on local records/opportunities/power, **never** on seeded delivery success. The receiver deduplicates separately. Inspect retired-but-unrecovered counts; sender queue empty does not prove recovery. Multiple distinct receivers use explicitly independent loss trials, an assumption that may be optimistic for correlated fades. Duplicate windows for one receiver do not create additional independent receivers.

A configured airtime fairness budget reserves a share for fresh updates, based on the union of supplied future compatible time windows after removing outages/expired permission intervals. Remaining history traffic cannot spend that reservation. If the requested fresh cadence cannot fit, modeled attempts are paced to the configured allocation. The calculation reserves conservatively across potential future geography; actual TX still requires its position/profile checks. This heuristic improves tracking availability under backlog pressure; it is not a global optimum.

Battery/capacitor updates account idle load, finite storage, charging conversion loss, bounded harvesting/spillage, radio energy and reserve/hysteresis. Unserved baseline energy is reported; sampling without available baseline power is counted as missed. No physical hardware power qualification is claimed. Energy balance residual is exported for checking.

## Batching interpretation

The trade study encodes actual supplied records for groups1–16 in the UI (API up to32), adds LoRaWAN overhead, and checks region/FOpts/dwell constraints. It reports collection delay, fresh interval, horizon airtime, ungrouped tail, expected records received, records lost per failed packet and group-loss variance. With independent packet failure probability `p`, loss variance per group is `k²*p*(1-p)`; members of a failed group are perfectly correlated. The recommendation minimizes airtime per record **subject to entered airtime/freshness limits**. It projects repeated observed group sizes, not a guaranteed compression rate or calibrated RF reliability.

## Reproduce and qualify

```sh
uv run --frozen pytest tests/test_telemetry.py -q
uv run --frozen python -m scripts.reproduce_telemetry --output /absolute/new/evidence-directory
# Optional synthetic scheduler stress case; no new NOAA acquisition:
uv run --frozen python -m scripts.reproduce_telemetry --long --output /absolute/new/stress-directory
```

The script refuses existing output directories and retains configuration, protocol vectors, binary archive, lossy summary, recovery events and hashed verification. The full browser suite owns isolated data/port8001. Full launch-weather72h, native Windows, actual compatible receivers, antenna/link margin, legal clearance, cold-power behavior, portable firmware, flash journaling and measured RF/energy calibration remain separate requirements.

Wire layouts, archive format and region tables: `TELEMETRY_PROTOCOL.md`. Pre-implementation findings: `TELEMETRY_AUDIT.md`. Final measured software-verification results: `TELEMETRY_VERIFICATION.md`.
