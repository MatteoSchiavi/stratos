"""Pinned LoRaWAN RP002-1.0.3 non-repeater uplink subset, not radio authorization."""

import math

from packages.telemetry.codec import encode
from packages.telemetry.models import BatchRequest, RadioRequest

TABLES = {
    "EU868": {
        0: (12, 125000, 51),
        1: (11, 125000, 51),
        2: (10, 125000, 51),
        3: (9, 125000, 115),
        4: (8, 125000, 242),
        5: (7, 125000, 242),
        6: (7, 250000, 242),
    },
    "US915": {
        0: (10, 125000, 11),
        1: (9, 125000, 53),
        2: (8, 125000, 125),
        3: (7, 125000, 242),
        4: (8, 500000, 242),
    },
}


def airtime_s(phy_bytes: int, sf: int, bandwidth_hz: int) -> float:
    if not 1 <= phy_bytes <= 255 or not 7 <= sf <= 12 or bandwidth_hz not in (125000, 250000, 500000):
        raise ValueError("Unsupported LoRa PHY parameters")
    symbol = 2**sf / bandwidth_hz
    de = int(symbol >= 0.016)
    payload_symbols = 8 + max(math.ceil((8 * phy_bytes - 4 * sf + 28 + 16) / (4 * (sf - 2 * de))) * 5, 0)
    return (8 + 4.25 + payload_symbols) * symbol


def validate_radio(request: RadioRequest) -> dict:
    dr = TABLES[request.region].get(request.data_rate)
    if dr is None:
        raise ValueError(
            "Unsupported regional uplink DR; downlink, FSK and LR-FHSS are not LoRa uplinks here"
        )
    sf, bandwidth, limit = dr
    available = max(0, limit - request.fopts_bytes)
    phy_bytes = request.application_bytes + 13 + request.fopts_bytes
    errors = []
    if request.application_bytes > available:
        errors.append(
            f"Application payload {request.application_bytes} B exceeds {available} B at {request.region} DR{request.data_rate}"
        )
    airtime = airtime_s(phy_bytes, sf, bandwidth) if phy_bytes <= 255 else None
    effective_dwell_ms = (
        request.dwell_limit_ms
        if request.dwell_limit_ms is not None
        else (400 if request.region == "US915" else None)
    )
    if effective_dwell_ms is not None and airtime is not None and airtime * 1000 > effective_dwell_ms + 1e-9:
        errors.append("Configured dwell-time limit exceeded")
    return {
        "region": request.region,
        "data_rate": request.data_rate,
        "sf": sf,
        "bandwidth_hz": bandwidth,
        "regional_revision": "RP002-1.0.3 non-repeater LoRa uplinks",
        "application_limit_bytes": available,
        "application_bytes": request.application_bytes,
        "fopts_bytes": request.fopts_bytes,
        "lorawan_overhead_bytes": 13 + request.fopts_bytes,
        "phy_bytes": phy_bytes,
        "airtime_s": airtime,
        "effective_dwell_limit_ms": effective_dwell_ms,
        "valid": not errors,
        "errors": errors,
        "scope": "Payload/modulation and optional dwell only; channel hopping, EIRP, national rules, network policy and airborne authorization need separate verification",
    }


def optimize_batch(request: BatchRequest) -> dict:
    candidates = []
    for count in range(1, len(request.observations) + 1):
        packet = encode("NAV+ENV" if count == 1 else "HISTORY", request.observations[:count])
        radio = validate_radio(request.radio.model_copy(update={"application_bytes": len(packet)}))
        interval = count * request.sample_interval_s
        # Whole collection groups within horizon, not a fractional successful packet.
        generated = math.floor(request.horizon_s / request.sample_interval_s)
        packets = generated // count
        airtime = radio["airtime_s"]
        used = packets * airtime if airtime is not None else None
        feasible = (
            radio["valid"]
            and used is not None
            and used <= request.available_airtime_s
            and interval <= request.max_fresh_interval_s
        )
        p = request.loss_probability
        candidates.append(
            {
                "batch_size": count,
                "packet_bytes": len(packet),
                "radio": radio,
                "fresh_interval_s": interval,
                "max_collection_delay_s": (count - 1) * request.sample_interval_s,
                "mean_collection_delay_s": (count - 1) * request.sample_interval_s / 2,
                "packets": packets,
                "ungrouped_tail_records": generated % count,
                "airtime_used_s": used,
                "airtime_per_record_s": airtime / count if airtime else None,
                "expected_received_records": packets * count * (1 - p),
                "lost_records_per_failed_packet": count,
                "loss_variance_per_packet": count**2 * p * (1 - p),
                "packet_overhead_bytes": radio["lorawan_overhead_bytes"],
                "feasible": feasible,
            }
        )
    feasible = [r for r in candidates if r["feasible"]]
    best = (
        min(feasible, key=lambda r: (r["airtime_per_record_s"], r["fresh_interval_s"])) if feasible else None
    )
    return {
        "candidates": candidates,
        "recommended_batch_size": best["batch_size"] if best else None,
        "objective": "Minimum modeled airtime per record subject to airtime and freshness constraints",
        "assumptions": "Actual supplied-record encoding sizes; repeated-size projection, independent packet losses, no retries. Losses within a batch are correlated. Sample loss probability is an input, not RF prediction.",
    }
