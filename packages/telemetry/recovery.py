"""Deterministic opportunity scheduler. No actual TX and no receiver-outcome oracle."""

import bisect
import math
import random
from collections import Counter, deque

from packages.domain.models import Cancelled
from packages.telemetry.archive import scientific_summary
from packages.telemetry.codec import encode
from packages.telemetry.models import Observation, RadioRequest, RecoveryRequest
from packages.telemetry.radio import validate_radio


def simulate_recovery(config: RecoveryRequest, progress=lambda f, m: None, cancelled=lambda: False) -> dict:
    rng = random.Random(config.seed)
    times = [r.time_s for r in config.positions]

    def position(t):
        i = bisect.bisect_right(times, t) - 1
        if i < 0:
            return None
        row = config.positions[i]
        return (
            row
            if row.fix_valid
            and row.clock_valid
            and row.latitude_deg is not None
            and t - row.time_s <= config.max_fix_age_s
            else None
        )

    def profiles_at(t):
        row = position(t)
        if row is None:
            return []
        return [
            p
            for p in config.profiles
            if p.start_s <= t < p.end_s
            and p.south <= row.latitude_deg <= p.north
            and (
                p.west <= row.longitude_deg <= p.east
                if p.west < p.east
                else row.longitude_deg >= p.west or row.longitude_deg <= p.east
            )
        ]

    # Reserve against the union of supplied future contact opportunities, removing
    # outages and time profiles without configured permission. Geometry is still
    # checked at TX; reservation conservatively includes uncertain future coverage.
    boundaries = sorted(
        {
            0.0,
            float(config.duration_s),
            *(
                v
                for w in [*config.contacts, *config.outages, *config.profiles]
                for v in (
                    max(0.0, min(w.start_s, config.duration_s)),
                    max(0.0, min(w.end_s, config.duration_s)),
                )
            ),
        }
    )
    contact_intervals: list[tuple[float, float]] = []
    for a, b in zip(boundaries, boundaries[1:], strict=False):
        midpoint = (a + b) / 2
        compatible = any(
            c.compatible
            and c.start_s <= midpoint < c.end_s
            and any(
                p.permission_configured and p.region == c.region and p.start_s <= midpoint < p.end_s
                for p in config.profiles
            )
            for c in config.contacts
        )
        if compatible and not any(o.start_s <= midpoint < o.end_s for o in config.outages):
            if contact_intervals and contact_intervals[-1][1] == a:
                contact_intervals[-1] = (contact_intervals[-1][0], b)
            else:
                contact_intervals.append((a, b))

    def future_contact_seconds(t):
        return sum(max(0, min(b, t + 86400) - max(a, t)) for a, b in contact_intervals)

    power = config.power
    battery = power.battery_initial_j
    capacitor = 0.5 * power.capacitor_f * power.initial_voltage_v**2
    cap_max = 0.5 * power.capacitor_f * power.max_voltage_v**2
    cap_sleep = 0.5 * power.capacitor_f * power.sleep_voltage_v**2
    cap_wake = 0.5 * power.capacitor_f * power.wake_voltage_v**2
    awake = capacitor >= cap_wake
    harvested = spilled = idle_used = conversion_loss = radio_used = unserved_idle = 0.0
    events: list[dict] = []
    trace: list[dict] = []
    records: list[Observation] = []
    delivered: set[int] = set()
    positions_delivered: set[int] = set()
    attempts: dict[int, int] = {}
    reasons: Counter = Counter()
    last_fresh, last_power_t, next_sample = -math.inf, 0.0, 0
    cooldown: dict[str, float] = {}
    rolling: deque = deque()
    rolling_airtime = 0.0
    busy_until = 0.0
    channel_use: dict[int, deque] = {}
    channel_pointer: dict[str, int] = {}
    fresh_costs: dict[tuple, float | None] = {}
    sampling_power_available = True
    missed_samples = 0
    peak_backlog = 0
    priority_count = -1
    important: set[int] = set()

    def advance(t):
        nonlocal \
            battery, \
            capacitor, \
            harvested, \
            spilled, \
            idle_used, \
            conversion_loss, \
            unserved_idle, \
            last_power_t, \
            awake
        dt = t - last_power_t
        if dt < 0:
            raise ValueError("Power clock moved backwards")
        produced = power.harvest_w * dt
        harvested += produced
        # Harvest supports idle first; remaining charge goes into battery.
        idle = power.idle_w * dt
        from_sun = min(produced, idle)
        need = idle - from_sun
        from_battery = min(battery, need)
        battery -= from_battery
        left = need - from_battery
        from_cap = min(capacitor, left)
        capacitor -= from_cap
        idle_used += from_sun + from_battery + from_cap
        deficit = left - from_cap
        unserved_idle += deficit
        sampling_power_available = deficit <= 1e-12 and battery + capacitor > 0
        incoming = produced - from_sun
        accepted = min(incoming, power.battery_capacity_j - battery)
        battery += accepted
        spilled += incoming - accepted
        transfer = min(
            max(0, battery - power.reserve_j),
            power.charge_w * dt,
            max(0, cap_max - capacitor) / power.efficiency,
        )
        battery -= transfer
        capacitor += transfer * power.efficiency
        conversion_loss += transfer * (1 - power.efficiency)
        if capacitor < cap_sleep or not sampling_power_available:
            awake = False
        if capacitor >= cap_wake and battery >= power.reserve_j and sampling_power_available:
            awake = True
        last_power_t = t

    instants = set(float(t) for t in range(0, config.duration_s, config.step_s))
    instants.update(float(t) for t in range(0, config.duration_s, config.sample_interval_s))
    instants.update(float(t) for t in times if 0 <= t < config.duration_s)
    for window in [*config.contacts, *config.outages, *config.profiles]:
        instants.update(t for t in (window.start_s, window.end_s) if 0 <= t < config.duration_s)
    if len(instants) > 40000:
        raise ValueError("Study exceeds40000 scheduling events")
    for tick, t in enumerate(sorted(instants)):
        if tick % 20 == 0:
            if cancelled():
                raise Cancelled("Recovery study cancelled")
            progress(t / config.duration_s, "Scheduling contacts, backlog and finite energy")
        advance(t)
        while next_sample <= t and next_sample < config.duration_s:
            if not sampling_power_available:
                missed_samples += 1
                next_sample += config.sample_interval_s
                continue
            row = position(next_sample)
            current_fix = row is not None and row.time_s == next_sample
            # A modeled sampling event, never relabel source inputs as live measurements.
            sample = Observation(
                time_s=next_sample,
                sequence=len(records) % 65536,
                latitude_deg=row.latitude_deg if row else None,
                longitude_deg=row.longitude_deg if row else None,
                altitude_m=row.altitude_m if current_fix else None,
                temperature_k=row.temperature_k if current_fix else None,
                pressure_pa=row.pressure_pa if current_fix else None,
                voltage_v=math.sqrt(2 * capacitor / power.capacitor_f),
                fix_valid=current_fix,
                clock_valid=True,
                origin="simulated",
            )
            records.append(sample)
            next_sample += config.sample_interval_s
        # Priorities depend on locally known data, not seeded reception outcomes.
        pending = [i for i in range(len(records)) if attempts.get(i, 0) < config.history_repeats]
        peak_backlog = max(peak_backlog, len(pending))
        if len(trace) < 1500 and (
            t % max(config.step_s, math.ceil(config.duration_s / 1200 / config.step_s) * config.step_s) == 0
        ):
            trace.append(
                {
                    "time_s": t,
                    "pending_records": len(pending),
                    "received_records": len(delivered),
                    "battery_j": battery,
                    "capacitor_v": math.sqrt(2 * capacitor / power.capacitor_f),
                }
            )
        if t < busy_until:
            reasons["radio_busy"] += 1
            continue
        region = profiles_at(t)
        if len(region) != 1:
            reasons["unknown_stale_or_ambiguous_region"] += 1
            continue
        profile = region[0]
        if not profile.permission_configured:
            reasons["permission_not_configured"] += 1
            continue
        if t < cooldown.get(profile.region, 0):
            reasons["regional_cooldown"] += 1
            continue
        if not awake or battery < power.reserve_j:
            reasons["power_sleep_or_reserve"] += 1
            continue
        contacts = [
            c
            for c in config.contacts
            if c.compatible and c.region == profile.region and c.start_s <= t < c.end_s
        ]
        if not contacts:
            reasons["no_compatible_contact"] += 1
            continue
        if not records:
            reasons["no_logged_record"] += 1
            continue
        fresh = t - last_fresh >= config.fresh_interval_s
        if fresh:
            # Latest position has priority; low storage uses the short emergency family.
            family = "EMERGENCY" if battery - power.reserve_j < 2 else "NAV+ENV"
            recent = [
                i
                for i in range(len(records))
                if records[i].fix_valid and t - records[i].time_s <= config.max_fix_age_s
            ]
            chosen = [recent[-1] if recent else len(records) - 1]
        elif pending:
            # Global extrema and trajectory changes are prioritized, with oldest-time tie breaking.
            # Bounded rolling summary prevents quadratic archive work at each scheduler tick.
            if priority_count != len(records):
                important = {r["index"] for r in scientific_summary(records[-64:], 100)["records"]}
                important = {len(records) - min(64, len(records)) + i for i in important}
                for field in ("altitude_m", "temperature_k", "voltage_v", "pressure_pa"):
                    known = [i for i, row in enumerate(records) if getattr(row, field) is not None]
                    if known:
                        important.add(min(known, key=lambda i: getattr(records[i], field)))
                        important.add(max(known, key=lambda i: getattr(records[i], field)))
                priority_count = len(records)
            chosen = sorted(pending, key=lambda i: (i not in important, records[i].time_s))[
                : config.history_batch
            ]
            chosen.sort()
            family = "HISTORY"
        else:
            reasons["nothing_due"] += 1
            continue
        families = (
            (["EMERGENCY"] if battery - power.reserve_j < 2 else ["NAV+ENV", "NAV", "EMERGENCY"])
            if fresh
            else ["HISTORY"]
        )
        options = []
        # Reduce history groups to fit actual regional payload/dwell/contact/energy limits.
        for family in families:
            for count in range(len(chosen), 0, -1):
                selected = chosen[:count]
                packet = encode(family, [records[i] for i in selected])
                for contact in contacts:
                    for dr in sorted(set(contact.data_rates)):
                        try:
                            check = validate_radio(
                                RadioRequest(
                                    region=profile.region,
                                    data_rate=dr,
                                    application_bytes=len(packet),
                                    fopts_bytes=config.fopts_bytes,
                                    dwell_limit_ms=profile.dwell_limit_ms,
                                )
                            )
                        except ValueError:
                            continue
                        if not check["valid"]:
                            continue
                        airtime = check["airtime_s"]
                        end = t + airtime
                        if end > min(contact.end_s, profile.end_s, config.duration_s):
                            continue
                        if any(t < outage.end_s and end > outage.start_s for outage in config.outages):
                            continue
                        end_profiles = profiles_at(end)
                        if len(end_profiles) != 1 or end_profiles[0] != profile:
                            continue
                        # Validate each retained fix crossed during the TX, not just the endpoint.
                        if any(
                            profiles_at(v) != [profile]
                            for v in times[bisect.bisect_right(times, t) : bisect.bisect_right(times, end)]
                        ):
                            continue
                        while rolling and rolling[0][0] <= t - 86400:
                            rolling_airtime -= rolling.popleft()[1]
                        if (
                            config.fair_use_s_per_24h is not None
                            and rolling_airtime + airtime > config.fair_use_s_per_24h + 1e-12
                        ):
                            continue
                        if config.fair_use_s_per_24h is not None:
                            future_seconds = future_contact_seconds(t)
                            fresh_budget = config.fair_use_s_per_24h * config.fresh_airtime_fraction
                            if fresh:
                                pacing_gap = (
                                    airtime * max(future_seconds, config.fresh_interval_s) / fresh_budget
                                )
                                if t - last_fresh + 1e-12 < pacing_gap:
                                    continue
                            else:
                                # Reserve the known future fresh demand (capped by
                                # the configured allocation), not a full day for a short study.
                                key = (profile.region, dr, profile.dwell_limit_ms)
                                if key not in fresh_costs:
                                    fresh_costs[key] = None
                                    for fresh_size in (24, 19, 11):
                                        fresh_check = validate_radio(
                                            RadioRequest(
                                                region=profile.region,
                                                data_rate=dr,
                                                application_bytes=fresh_size,
                                                fopts_bytes=config.fopts_bytes,
                                                dwell_limit_ms=profile.dwell_limit_ms,
                                            )
                                        )
                                        if fresh_check["valid"]:
                                            fresh_costs[key] = fresh_check["airtime_s"]
                                            break
                                opportunities = sum(
                                    math.ceil(max(0, min(b, t + 86400) - max(a, t)) / config.fresh_interval_s)
                                    for a, b in contact_intervals
                                )
                                fresh_demand = opportunities * (fresh_costs[key] or airtime)
                                reserve = min(fresh_budget, fresh_demand)
                                # Already-spent fresh airtime also reduces remaining capacity.
                                if rolling_airtime + airtime + reserve > config.fair_use_s_per_24h + 1e-12:
                                    continue
                        energy = power.tx_w * airtime + power.rx_allowance_j
                        if capacitor - energy < cap_sleep - 1e-12:
                            continue
                        if profile.region == "US915":
                            frequencies = (
                                [903000000 + i * 1600000 for i in range(8)]
                                if dr == 4
                                else [902300000 + i * 200000 for i in range(64)]
                            )
                        else:
                            frequencies = [868100000, 868300000, 868500000]
                        start_channel = channel_pointer.get(profile.region, 0) % len(frequencies)
                        chosen_frequency = None
                        for channel_offset in range(len(frequencies)):
                            frequency = frequencies[(start_channel + channel_offset) % len(frequencies)]
                            if contact.channels_hz is not None and frequency not in contact.channels_hz:
                                continue
                            use = channel_use.get(frequency, deque())
                            occupancy = sum(
                                max(0, end_old - max(start_old, end - 20))
                                for start_old, end_old in use
                                if end_old > end - 20
                            )
                            if profile.region != "US915" or occupancy + airtime <= 0.4 + 1e-12:
                                chosen_frequency = frequency
                                break
                        if chosen_frequency is None:
                            continue
                        options.append(
                            (
                                energy / count,
                                airtime,
                                contact.receiver_id,
                                dr,
                                selected,
                                packet,
                                check,
                                contact,
                                energy,
                                chosen_frequency,
                            )
                        )
                if options:
                    break
            if options:
                break
        if not options:
            reasons["payload_airtime_outage_region_or_energy_constraint"] += 1
            continue
        _, airtime, _, dr, selected, packet, check, contact, energy, frequency = min(
            options, key=lambda o: o[:4]
        )
        channel_pointer[profile.region] = channel_pointer.get(profile.region, 0) + 1
        use = channel_use.setdefault(frequency, deque())
        while use and use[0][1] <= t - 20:
            use.popleft()
        use.append((t, t + airtime))
        capacitor -= energy
        radio_used += energy
        busy_until = t + airtime
        cooldown[profile.region] = t + airtime / profile.duty_fraction
        rolling.append((t, airtime, fresh))
        rolling_airtime += airtime
        if fresh:
            last_fresh = t
        else:
            for i in selected:
                attempts[i] = attempts.get(i, 0) + 1
        # One RF broadcast can be heard by several compatible receivers. Outcomes do not
        # influence sender queues/repeats. Per-receiver independent losses are assumptions.
        heard = []
        eligible = [
            c
            for c in contacts
            if dr in c.data_rates
            and t + airtime <= c.end_s
            and (c.channels_hz is None or frequency in c.channels_hz)
        ]
        for receiver_id in sorted({c.receiver_id for c in eligible}):
            copies = [c for c in eligible if c.receiver_id == receiver_id]
            p = max(c.loss_probability for c in copies)  # conservative duplicate-source merge
            if rng.random() >= p:
                heard.append(receiver_id)
        if heard:
            positions_delivered.update(i for i in selected if records[i].fix_valid)
            if family in ("NAV+ENV", "HISTORY"):
                delivered.update(selected)
        events.append(
            {
                "time_s": t,
                "end_s": t + airtime,
                "family": family,
                "region": profile.region,
                "frequency_hz": frequency,
                "profile": profile.name,
                "receiver_ids": heard,
                "opportunity_receiver_ids": sorted({c.receiver_id for c in eligible}),
                "contact_evidence": sorted({c.evidence for c in eligible}),
                "data_rate": dr,
                "sf": check["sf"],
                "bandwidth_hz": check["bandwidth_hz"],
                "packet_hex": packet.hex(),
                "application_bytes": len(packet),
                "phy_bytes": check["phy_bytes"],
                "airtime_s": airtime,
                "energy_j": energy,
                "record_indices": selected,
                "received": bool(heard),
                "decision": "fresh_position_due" if fresh else "priority_history_fixed_repeat_policy",
            }
        )
        if len(events) >= 5000:
            raise ValueError("Study exceeds5000 transmission events; increase intervals")
    advance(config.duration_s)
    retired = {i for i, n in attempts.items() if n >= config.history_repeats}
    initial = power.battery_initial_j + 0.5 * power.capacitor_f * power.initial_voltage_v**2
    residual = (
        initial + harvested - (battery + capacitor + spilled + idle_used + conversion_loss + radio_used)
    )
    total_airtime = sum(e["airtime_s"] for e in events)
    first_fix = latest_fix_time = previous_delivery = None
    max_age = integral_age = 0.0
    for event in events:
        if not event["received"]:
            continue
        known = [
            (records[i].time_s // 60 * 60 if event["family"] == "EMERGENCY" else records[i].time_s)
            for i in event["record_indices"]
            if records[i].fix_valid and records[i].clock_valid
        ]
        if not known:
            continue
        sample_time, arrival = max(known), event["end_s"]
        if latest_fix_time is not None and sample_time <= latest_fix_time:
            continue
        if previous_delivery is not None:
            integral_age += (
                (arrival - latest_fix_time) ** 2 - (previous_delivery - latest_fix_time) ** 2
            ) / 2
            max_age = max(max_age, arrival - latest_fix_time)
        else:
            first_fix = arrival
        latest_fix_time, previous_delivery = sample_time, arrival
    if previous_delivery is not None and latest_fix_time is not None:
        integral_age += (
            (config.duration_s - latest_fix_time) ** 2 - (previous_delivery - latest_fix_time) ** 2
        ) / 2
        max_age = max(max_age, config.duration_s - latest_fix_time)
    freshness = {
        "first_received_position_s": first_fix,
        "max_known_position_age_s": max_age if first_fix is not None else None,
        "mean_known_position_age_s": integral_age / (config.duration_s - first_fix)
        if first_fix is not None and first_fix < config.duration_s
        else None,
        "final_position_age_s": config.duration_s - latest_fix_time if latest_fix_time is not None else None,
    }

    return {
        "schema_version": 1,
        "quality": "simulated_assumptions_not_measured_reception",
        "seed": config.seed,
        "freshness": freshness,
        "metrics": {
            "generated_records": len(records),
            "missed_samples_power": missed_samples,
            "received_records": len(delivered),
            "received_positions": len(positions_delivered),
            "unrecovered_records": len(records) - len(delivered),
            "sender_pending_records": len(records) - len(retired),
            "retired_unrecovered_records": len(retired - delivered),
            "peak_sender_backlog": peak_backlog,
            "transmissions": len(events),
            "airtime_s": total_airtime,
            "radio_energy_j": radio_used,
            "battery_remaining_j": battery,
            "capacitor_final_v": math.sqrt(2 * capacitor / power.capacitor_f),
            "harvested_j": harvested,
            "idle_energy_j": idle_used,
            "unserved_idle_j": unserved_idle,
            "conversion_loss_j": conversion_loss,
            "spilled_j": spilled,
            "energy_balance_residual_j": residual,
        },
        "blocked_steps": dict(reasons),
        "events": events,
        "timeline": trace,
        "records": [r.model_dump() for r in records],
        "limitations": [
            "Entered/imported receiver windows and loss assumptions; no RF/terrain/gateway discovery model.",
            "Unconfirmed fixed-repeat policy; receiver outcomes never feed sender decisions. Quantized radio recovery is distinct from original local records.",
            "Configured test geofences are not authoritative borders; no actual transmitter or legal authorization.",
            "Lumped battery/capacitor power with assumed loads, RX allowance and constant harvest; no ESR, thermal or bench validation.",
        ],
    }
