# STRATOS telemetry protocol v1

This is an application payload codec, not a LoRaWAN stack or firmware release. All multibyte fixed fields are big endian. Application FPort42 is the proposed integration convention; FPort, DevAddr, LoRaWAN FCnt/MIC and the explicit mission/session UTC epoch are external context. No radio is operated by this application.

## Header and validity

Header bits7–4 contain version1. Bits3–2 must be zero. Bits1–0 identify NAV0, NAV+ENV1, HISTORY2, EMERGENCY3. Unknown versions/reserved bits/lengths are rejected.

Validity byte bits:0 position,1 clock,2 altitude,3 voltage,4 temperature,5 pressure. Bits6–7 are reserved. NAV permits bits0–3; EMERGENCY permits bits0–1. Absent data use canonical sentinels; a flag/sentinel contradiction is rejected. An invalid clock must never establish a fix's age. Packet sequence numbers are application counters; they provide neither cryptographic replay protection nor a globally unique observation ID.

Coordinate codes use unsigned24 with `Q=16,777,214`; `16,777,215` is missing. `lat_code=round((lat+90)*Q/180)` and `lon_code=round((lon+180)*Q/360)`. Decoding applies the inverse mapping. Round nearest, ties to even. Both global endpoints are representable. Maximum angular rounding error is90/Q degrees latitude and180/Q longitude (~0.60m and1.20m at the equator); this is encoding resolution, not GNSS accuracy. +180/-180 represent the same meridian with distinct codes.

## Fixed packet layouts

Offsets are zero based; sizes include the application CRC where present.

| Field | NAV19B | NAV+ENV24B | Encoding |
| --- | --- | --- | --- |
| Header |0|0|u8, version/type|
| Validity |1|1|u8|
| Sequence |2–3|2–3|u16, explicit modulo65536|
| Mission time |4–6|4–6|u24 seconds from explicit epoch|
| Latitude |7–9|7–9|global u24|
| Longitude |10–12|10–12|global u24|
| Geometric MSL altitude |13–14|13–14|i16 metres; -32768 missing, valid -32767…32767|
| Storage voltage |15–16|15–16|u16 millivolts;65535 missing|
| Temperature |—|17–18|i16 centidegrees Celsius, K = code/100+273.15; -32768 missing|
| Pressure |—|19–21|u24 Pa;16777215 missing|
| CRC |17–18|22–23|CRC-16/CCITT-FALSE over all preceding bytes|

The domain model accepts temperature0–500K; exact sensor calibration/resolution is external. Voltage is0–65.534V and pressure0–16,777,214Pa. Encoding quantizes physical values; it is not a lossless scientific archive. The CRC uses polynomial0x1021, initial0xffff, no reflection, no final XOR. It detects corruption, not forgery.

### EMERGENCY11B

| Offset | Field |
| --- | --- |
|0|Header0x13|
|1|Position/clock validity only|
|2|Application sequence modulo256|
|3–4|u16 whole minutes since explicit mission epoch, floor(seconds/60)|
|5–7|Latitude u24|
|8–10|Longitude u24|

This family intentionally omits altitude, voltage and environment. It has **no application CRC**; an externally verified LoRaWAN MIC is required before treating a received packet as authenticated transport. Raw codec success does not establish integrity or reception. Sequence8 wraps after256 packets. Time is limited to65535 minutes (~45.5days), with up to59s quantization. No implicit rollover inference is allowed; longer missions need a new explicitly associated session or protocol version. NAV time24 is limited to16,777,215 seconds (~194days).

### HISTORY variable length

Header0x12, count u8(1–32), delta records, then CRC16. Each record contains nine integers in this order:

`time_seconds, sequence, validity, latitude_code, longitude_code, altitude_metres, voltage_mV, temperature_centiC, pressure_Pa`.

For each column, subtract the previous record's integer; the first record subtracts zero. Zigzag encode the signed difference (`2*x` if nonnegative, `-2*x-1` otherwise), then canonical unsigned LEB128. Delta state resets at every packet; a lost packet cannot corrupt a later packet's decoding. Negative sequence deltas preserve explicit65535→0 wrap. Missing sentinels participate in deltas. Reject noncanonical/overflow/truncated varints, invalid decoded ranges, contradictory flags, trailing bytes and non-increasing times. Batch actual byte size must be validated against the regional application limit; no fixed “records per packet” capacity is assumed.

## Regional airtime contract

Pinned baseline: LoRaWAN **RP002-1.0.3**, non-repeater-compatible uplinks. This is deliberately versioned rather than labelled universally current. EU FSK and LR-FHSS and US downlinks are not supported by this LoRa calculator.

| Region | DR | SF | BW kHz | Maximum application bytes, FOpts0 |
| --- | --- | --- | --- | --- |
|EU868|0/1/2|12/11/10|125|51|
|EU868|3|9|125|115|
|EU868|4/5|8/7|125|242|
|EU868|6|7|250|242|
|US915|0|10|125|11|
|US915|1|9|125|53|
|US915|2|8|125|125|
|US915|3|7|125|242|
|US915|4|8|500|242|

FOpts(0–15B) reduces application capacity by its actual length. Physical payload length is application+13+FOpts (MHDR1, FHDR7 minimum, FPort1, MIC4). LoRa PHY CRC is included in the symbol equation, not incorrectly added to PHYPayload bytes. Explicit header, coding4/5, CRC on, preamble8; low-data-rate optimization when symbol duration≥16ms.

`Ts=2**SF/BW`; `Npayload=8+max(ceil((8*PL-4*SF+28+16)/(4*(SF-2*DE)))*5,0)`; `T=(8+4.25+Npayload)*Ts`.

Independent32B PHY vectors: SF7/125=.071936s, SF9/125=.246784s, SF10/125=.452608s, SF12/125=1.810432s. US DR0 EMERGENCY11B has24B PHY and fits the conservative400ms cap; NAV19B cannot fit DR0's payload limit. The optional explicit dwell limit may be stricter; US validation defaults conservatively to400ms, while EU does not inherit it.

Scheduler EU profile supports the shared868.1/868.3/868.5MHz1% sub-band only, accounting the full transmitter cooldown rather than multiplying allowance by channel count. US rotates supported902.3MHz+0.2MHz*n (64 channels, DR0–3) or903MHz+1.6MHz*n (8 channels, DR4), intersects declared receiver channel masks and conservatively caps each channel at400ms in any modeled20s rolling interval. This is a bounded planning profile, not a complete FCC/ETSI conformance implementation: actual channel configuration, EIRP, modulation certification, airborne restrictions, permissions and current national rules remain external requirements. TTN airtime fairness is an independent optional rolling24h policy budget.

Research source copies, original upstream licence and SHA-256: `research/telemetry/`. Source tables are secondary implementation cross-checks, not legal authority.

## Lossless archive STLA v1

This is a local typed-observation artifact, independent of radio quantization and the lossy summary. It retains original validated float64 JSON representations, nulls, provenance, flags, ordering and sequence values. It is not a power-loss-qualified flash journal.

Header: magic `STLA`+version byte1(5B), record count u32(4B), SHA-256 of canonical original record array(32B), context length u16(2B), context SHA-256(32B), canonical context JSON (`epoch_utc`: explicit ISO UTC or null meaning unspecified relative time). Corruption of epoch context is checked independently. No UTC is fabricated when absent.

Blocks contain up to64 records: count u16, uncompressed length u32, compressed length u32, CRC32 of uncompressed delta block u32, then zlib bytes. The first canonical JSON row has zero prefix; subsequent rows retain the longest matching byte prefix of the previous row. Each entry stores prefix length and suffix byte length as canonical unsigned LEB128 followed by suffix bytes. Prefix state resets each block. Canonical rows use sorted keys, compact separators and finite JSON numbers; the array hash includes array brackets/commas.

Decoder bounds:5000 records,4MiB total file/expanded blocks,1024B context, canonical varints, exact inventories/counts, block CRC and final original-record SHA. It rejects incomplete/corrupt archives rather than silently publishing partial recovery. A future journal/prefix-salvage feature requires its own qualification.

Scientific summaries are separate exports. They retain endpoints, global scalar extrema, validity transitions, clock discontinuities and time-parametrized WGS84 path deviations above a stated tolerance. Invalid clocks/positions break path segments. Intermediate scalar behavior may be lost. A100000-geodesic-evaluation cap may make a summary unavailable; a valid lossless archive is still saved.
