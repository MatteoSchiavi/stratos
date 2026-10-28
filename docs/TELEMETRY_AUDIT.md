# Telemetry and recovery design audit — 28 October 2026

The existing P0/P1 repository has a working immutable mission/trajectory pipeline, NOAA cache, offline map and saved-study comparison. It has no telemetry wire protocol, radio profiles, receiver database, transmitter, flash journal or energy qualification. This request explicitly authorizes a bounded telemetry/recovery engineering slice beyond the earlier P1-only milestone; it does not complete P2–P7.

## Technical findings before implementation

- Packet sizes alone do not define interoperable firmware. Define a versioned byte layout, byte order, coordinate rounding, ranges, unknown values, CRC behavior, epoch/session context and rollover handling.24-bit coordinates have finite quantization (~0.6m latitude/~1.2m longitude maximum rounding error at the equator). Neither that resolution nor successful decoding proves GNSS accuracy.
- EMERGENCY11B cannot hold every NAV field and integrity wrapper. Reserve global coordinates and explicit time/sequence/validity; omit altitude/environment. It relies on verified LoRaWAN MIC at transport, rather than claiming application CRC protection. Mission/session epoch is configured out of band. Application sequence counters are not LoRaWAN FCnt and must not provide replay protection.
- Region-specific DR indices are essential. EU DR0=SF12/125kHz; US DR0=SF10/125kHz with only11B application payload, US DR4=SF8/500kHz. FOpts reduces available application bytes and increases PHY airtime. Downlink/FSK/LR-FHSS rates are excluded explicitly. Pin the supported RP002-1.0.3 non-repeater baseline instead of claiming all revisions.
- US frequency hopping/dwell/channel plans and EU sub-band duty cycle cannot be certified from packet length. Validate modeled payload/modulation and optional400ms dwell plus conservative configured per-profile cooldown; require an explicit jurisdiction profile for scheduling. TTN30s/day fair-use is an optional, separate rolling budget, never a legal entitlement. Airtime includes13B minimum LoRaWAN overhead, configurable FOpts, explicit header/CRC, coding4/5 and DE at long symbol durations.
- Grouping increases freshness latency and correlates loss of records. Optimize using actual encoded bytes and expose lost-record variance and maximum loss per failed packet, not just compression ratio. Predictions use stated independent-loss assumptions, not invented RF coverage.
- A lossless archive must preserve original typed observations (including float values), independently of radio quantization and scientific downsampling. Use bounded, checksummed blocks with delta encoding and compression. Generate lossy summaries separately, pinning endpoints, extrema, validity transitions and significant trajectory changes; never overwrite the archive.
- Geographic gateway proximity is not observed contact. Contact windows must carry receiver identity, compatibility, source and evidence class; only their intersection with valid geographic profiles/outage-free intervals is eligible. Unknown, overlapping or stale-position regions block scheduling. Entered rectangles are configured test geofences, not an authoritative worldwide jurisdiction database.
- A scheduler must not learn whether an unconfirmed packet was received. Use a fixed repeat policy independent of seeded packet outcomes, deduplicate at the receiver, keep local archives intact, and report retired-but-unrecovered records. Full on-air duration must fit contacts/regions/outages.
- Battery/capacitor energy and hysteresis are bounded illustrative models until measured parameters exist. Include idle load, harvesting, conversion loss, RX allowance and transmission energy; preserve reserve and capacitor thresholds. No solar/thermal/ESR or radio-hardware qualification follows.

## Implementation boundaries

Pure Python modules under packages/telemetry; typed bounded API requests; immutable analysis records in existing SQLite Record storage; raw codec/archive exports; no hardware/network transmission. Independent protocol vectors, coordinate boundaries, airtime vectors, regional differences, corruption tests, compression round trips, contact/outage/permission gates, no-oracle scheduling and energy conservation precede UI integration.

UI: retain functioning trajectory/weather tools, remove deferred navigation fillers, show contextual actions, add a compact workflow guide and separate protocol, recovery and archive tasks. Advanced parameters are disclosed on demand. All demo contacts/energy/packet-loss assumptions stay labelled.

## Research provenance

Fetched upstream brocaar/lorawan band_eu863_870.go and band_us902_928.go over HTTPS on28 October2026; exact source copies and SHA-256 are retained under docs/research/telemetry. Those tables explicitly identify RP002-1.0.3. These are secondary implementation cross-checks, not national radio authorizations. The LoRa symbol-time equation follows Semtech AN1200.13; references and numerical vectors are documented with the module. Current official regulatory amendments and actual receiver/hardware behavior remain operator/bench requirements.


## Verification-driven refinement

The first72h synthetic stress run exposed history traffic exhausting the rolling airtime budget early. The scheduler now reserves a configurable fresh-airtime fraction against the union of upcoming compatible time windows (minus outages/expired permissions), paces infeasible fresh cadences and uses the remainder for history. Geometry is still checked at each actual modeled TX. The final regression verifies fresh tracking survives a large backlog. Saved-trajectory input provenance is pinned to its original simulation ID, output hash and epoch; mismatches are rejected.
