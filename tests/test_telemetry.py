"""Independent wire, regional, archive and scheduling invariants; no radio reception claim."""

import binascii
import copy
import hashlib
import random
import struct

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.domain.models import Cancelled, digest
from packages.telemetry.archive import canonical_records, decode_archive, encode_archive, scientific_summary
from packages.telemetry.codec import COORD_MAX, decode, encode, read_varint
from packages.telemetry.examples import example_study
from packages.telemetry.models import BatchRequest, Observation, RadioRequest, RecoveryRequest
from packages.telemetry.radio import airtime_s, optimize_batch, validate_radio
from packages.telemetry.recovery import simulate_recovery
from services.api.main import create_app
from services.api.worker import run_one


def observation(**changes):
    return Observation(
        time_s=60,
        sequence=513,
        latitude_deg=0,
        longitude_deg=0,
        altitude_m=100,
        voltage_v=3.3,
        temperature_k=273.15,
        pressure_pa=100000,
        **changes,
    )


def test_fixed_packet_sizes_and_independent_reference_bytes():
    row = observation()
    # Hand-assembled fixed fields, unsigned24 global zero=0x7fffff; CRC checked separately.
    nav_body = bytes.fromhex("100f020100003c7fffff7fffff00640ce4")
    # 17 body bytes, prefix declared above; byte offset layout must agree with spec.
    assert len(nav_body) == 17
    assert encode("NAV", [row]) == nav_body + struct.pack(">H", binascii.crc_hqx(nav_body, 0xFFFF))
    assert len(encode("NAV", [row])) == 19
    assert len(encode("NAV+ENV", [row])) == 24
    assert encode("EMERGENCY", [row]).hex() == "13030100017fffff7fffff"
    decoded = decode(encode("NAV+ENV", [row]))["observations"][0]
    assert decoded["latitude_deg"] == 0 and decoded["longitude_deg"] == 0
    assert decoded["temperature_k"] == 273.15 and decoded["voltage_v"] == 3.3


@pytest.mark.parametrize("family", ["NAV", "NAV+ENV", "HISTORY"])
def test_crc_detects_every_single_bit_corruption(family):
    data = encode(family, [observation()])
    for i in range(len(data) * 8):
        damaged = bytearray(data)
        damaged[i // 8] ^= 1 << (i % 8)
        with pytest.raises(ValueError):
            decode(bytes(damaged))


def test_global_coordinate_quantization_and_dateline():
    rng = random.Random(91)
    for lat, lon in [(-90, -180), (90, 180), (0, 0)] + [
        (rng.uniform(-90, 90), rng.uniform(-180, 180)) for _ in range(300)
    ]:
        row = observation().model_copy(update={"latitude_deg": lat, "longitude_deg": lon})
        decoded = decode(encode("NAV", [row]))["observations"][0]
        assert abs(decoded["latitude_deg"] - lat) <= 90 / COORD_MAX + 1e-12
        assert abs(decoded["longitude_deg"] - lon) <= 180 / COORD_MAX + 1e-12


def test_history_roundtrip_validity_wrap_and_bad_frames():
    rows = [
        observation().model_copy(update={"sequence": 65535, "time_s": 0}),
        observation().model_copy(
            update={"sequence": 0, "time_s": 60, "temperature_k": None, "fix_valid": False}
        ),
        observation().model_copy(update={"sequence": 1, "time_s": 120}),
    ]
    decoded = decode(encode("HISTORY", rows))["observations"]
    assert [r["sequence"] for r in decoded] == [65535, 0, 1]
    assert decoded[1]["latitude_deg"] is None and decoded[1]["temperature_k"] is None
    for raw in (b"", b"\x20", b"\x14", b"\x13" * 12):
        with pytest.raises(ValueError):
            decode(raw)
    with pytest.raises(ValueError):
        encode("HISTORY", rows[::-1])
    with pytest.raises(ValueError):
        encode("NAV", rows)
    with pytest.raises(ValueError):
        read_varint(b"\x80\x00", 0)
    with pytest.raises(ValueError):
        read_varint(b"\xff" * 11, 0)
    with pytest.raises(ValueError):
        encode("EMERGENCY", [observation().model_copy(update={"time_s": 65536 * 60})])
    packet = bytearray(encode("NAV", [observation()]))
    packet[1] |= 64
    packet[-2:] = struct.pack(">H", binascii.crc_hqx(packet[:-2], 0xFFFF))
    with pytest.raises(ValueError):
        decode(bytes(packet))


@pytest.mark.parametrize("sf,expected", [(7, 0.071936), (9, 0.246784), (10, 0.452608), (12, 1.810432)])
def test_semtech_symbol_time_reference_vectors(sf, expected):
    # 32-byte PHY; CR4/5, explicit header, CRC on, eight preamble symbols.
    assert airtime_s(32, sf, 125000) == pytest.approx(expected, abs=1e-12)


def test_regions_differ_and_fopts_dwell_are_accounted():
    eu = validate_radio(RadioRequest(region="EU868", data_rate=0, application_bytes=19))
    us = validate_radio(RadioRequest(region="US915", data_rate=0, application_bytes=19))
    assert eu["valid"] and eu["sf"] == 12 and eu["application_limit_bytes"] == 51
    assert not us["valid"] and us["sf"] == 10 and us["application_limit_bytes"] == 11
    assert validate_radio(
        RadioRequest(region="US915", data_rate=0, application_bytes=11, dwell_limit_ms=400)
    )["valid"]
    assert not validate_radio(RadioRequest(region="US915", data_rate=0, application_bytes=11, fopts_bytes=1))[
        "valid"
    ]
    assert validate_radio(RadioRequest(region="US915", data_rate=4))["bandwidth_hz"] == 500000
    assert not validate_radio(RadioRequest(region="EU868", data_rate=0, dwell_limit_ms=400))["valid"]
    with pytest.raises(ValueError):
        validate_radio(RadioRequest(region="US915", data_rate=8))


def test_batching_uses_encoded_bytes_and_reports_group_loss():
    rows = example_study().positions[:8]
    request = BatchRequest(observations=rows, available_airtime_s=100)
    result = optimize_batch(request)
    last = result["candidates"][-1]
    assert last["packet_bytes"] == len(encode("HISTORY", rows))
    assert last["lost_records_per_failed_packet"] == 8
    assert last["loss_variance_per_packet"] == pytest.approx(64 * 0.2 * 0.8)
    assert last["max_collection_delay_s"] == 420
    impossible = request.model_copy(update={"radio": RadioRequest(region="US915", data_rate=0)})
    assert optimize_batch(impossible)["recommended_batch_size"] is None


def test_archive_is_lossless_before_radio_quantization_and_rejects_corruption():
    rows = example_study().positions
    rows[2] = rows[2].model_copy(update={"latitude_deg": -0.0, "temperature_k": 225.1234567890123})
    raw = encode_archive(rows)
    restored = decode_archive(raw)
    assert canonical_records(restored) == canonical_records(rows)
    assert struct.pack(">d", restored[2].latitude_deg) == struct.pack(">d", -0.0)
    assert len(raw) < len(canonical_records(rows))
    for changed in (raw[:-1], raw + b"x", bytes([raw[0] ^ 1]) + raw[1:], raw[:30] + b"x" + raw[31:]):
        with pytest.raises(ValueError):
            decode_archive(changed)
    # Length bomb rejected before allocating its declared expansion.
    damaged = bytearray(raw)
    start = 75 + int.from_bytes(raw[41:43], "big")
    damaged[start + 2 : start + 6] = (10**9).to_bytes(4, "big")
    with pytest.raises(ValueError):
        decode_archive(bytes(damaged))


def test_lossy_summary_retains_extrema_turns_and_invalid_transitions():
    rows = [
        observation().model_copy(
            update={
                "time_s": i * 60,
                "sequence": i,
                "latitude_deg": lat,
                "longitude_deg": lon,
                "temperature_k": temp,
            }
        )
        for i, (lat, lon, temp) in enumerate([(0, 0, 270), (0, 0.1, 280), (0.1, 0.1, 250), (0.1, 0.2, 270)])
    ]
    result = scientific_summary(rows, 100)
    assert {r["index"] for r in result["records"]} == {0, 1, 2, 3}
    assert "temperature_k_maximum" in next(r for r in result["records"] if r["index"] == 1)["reasons"]
    rows[1] = rows[1].model_copy(update={"fix_valid": False})
    assert {0, 1, 2}.issubset({r["index"] for r in scientific_summary(rows)["records"]})


def test_scheduler_contacts_outages_cooldown_and_power_conservation():
    config = example_study()
    result = simulate_recovery(config)
    assert result["metrics"]["transmissions"] > 0
    assert abs(result["metrics"]["energy_balance_residual_j"]) < 1e-8
    previous = None
    for event in result["events"]:
        assert any(c.start_s <= event["time_s"] < event["end_s"] <= c.end_s for c in config.contacts)
        assert not any(event["time_s"] < o.end_s and event["end_s"] > o.start_s for o in config.outages)
        if previous:
            assert event["time_s"] >= previous["time_s"] + previous["airtime_s"] / 0.01 - 1e-8
        previous = event
        assert len(bytes.fromhex(event["packet_hex"])) == event["application_bytes"]
        assert decode(bytes.fromhex(event["packet_hex"]))["family"] == event["family"]
    assert all(t["battery_j"] >= 0 and t["capacitor_v"] >= 0 for t in result["timeline"])


@pytest.mark.parametrize("gate", ["contacts", "permission", "unknown", "stale", "overlap", "outage", "power"])
def test_scheduler_fails_closed(gate):
    values = example_study().model_dump()
    if gate == "contacts":
        values["contacts"] = []
    if gate == "permission":
        values["profiles"][0]["permission_configured"] = False
    if gate == "unknown":
        values["profiles"] = []
    if gate == "stale":
        values["positions"] = [dict(values["positions"][0], time_s=3601)]
    if gate == "overlap":
        values["profiles"].append(copy.deepcopy(values["profiles"][0]))
    if gate == "outage":
        values["outages"] = [{"start_s": 0, "end_s": 3600}]
    if gate == "power":
        values["power"].update(initial_voltage_v=3, battery_initial_j=0, reserve_j=0, harvest_w=0)
    result = simulate_recovery(RecoveryRequest.model_validate(values))
    assert result["events"] == []
    assert abs(result["metrics"]["energy_balance_residual_j"]) < 1e-8


def test_sender_does_not_know_unconfirmed_delivery_and_recovery_deduplicates():
    config = example_study().model_dump()
    outputs = []
    for p in (0, 1):
        for c in config["contacts"]:
            c["loss_probability"] = p
        outputs.append(simulate_recovery(RecoveryRequest.model_validate(config)))

    def schedule(v):
        return [(e["time_s"], e["packet_hex"], e["record_indices"]) for e in v["events"]]

    assert schedule(outputs[0]) == schedule(outputs[1])
    assert outputs[0]["metrics"]["received_records"] <= outputs[0]["metrics"]["generated_records"]
    assert outputs[1]["metrics"]["received_records"] == 0
    assert outputs[1]["metrics"]["retired_unrecovered_records"] > 0


def test_us915_dr0_falls_back_to_emergency_and_no_full_science_claim():
    values = example_study().model_dump()
    values["profiles"][0].update(region="US915", duty_fraction=1, dwell_limit_ms=400)
    for c in values["contacts"]:
        c.update(region="US915", data_rates=[0], loss_probability=0)
    result = simulate_recovery(RecoveryRequest.model_validate(values))
    assert result["events"] and all(e["family"] == "EMERGENCY" for e in result["events"])
    assert result["metrics"]["received_records"] == 0 and result["metrics"]["received_positions"] > 0
    with pytest.raises(Cancelled):
        simulate_recovery(example_study(), cancelled=lambda: True)


def test_invalid_model_bounds_and_thresholds():
    with pytest.raises(ValidationError):
        Observation(time_s=0, sequence=0, latitude_deg=1)
    values = example_study().model_dump()
    values["power"]["wake_voltage_v"] = 3
    with pytest.raises(ValidationError):
        RecoveryRequest.model_validate(values)
    values = example_study().model_dump()
    values["duration_s"] = 259200
    values["step_s"] = 1
    with pytest.raises(ValidationError):
        RecoveryRequest.model_validate(values)


def test_api_worker_archive_and_restart_workflow(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        run_one(app.state.sessions, tmp_path)
        config = client.get("/api/telemetry/example").json()
        packet = client.post(
            "/api/telemetry/codec/encode", json={"family": "NAV+ENV", "observations": config["positions"][:1]}
        )
        assert packet.status_code == 200 and packet.json()["bytes"] == 24
        assert (
            client.post("/api/telemetry/codec/decode", json={"hex": packet.json()["hex"]}).status_code == 200
        )
        job = client.post("/api/telemetry/studies", json=config)
        assert job.status_code == 202
        run_one(app.state.sessions, tmp_path)
        completed = client.get("/api/jobs/" + job.json()["id"]).json()
        assert completed["status"] == "completed", completed
        ident = completed["result_id"]
        evidence = client.get("/api/telemetry/studies/" + ident).json()
        assert evidence["output_sha256"] == digest(evidence["output"])
        created = client.post("/api/telemetry/archives", json={"observations": config["positions"]})
        assert created.status_code == 201, created.text
        archive_id = created.json()["id"]
        raw = client.get("/api/telemetry/archives/" + archive_id + "/binary").content
        assert hashlib.sha256(raw).hexdigest() == created.json()["archive_sha256"]
        decoded = client.post(
            "/api/telemetry/archives/decode",
            content=raw,
            headers={"content-type": "application/octet-stream"},
        )
        assert decoded.status_code == 200 and decoded.json()["observations"] == config["positions"]
        simulation = client.get("/api/simulations").json()[0]
        source = client.get("/api/telemetry/sources/" + simulation["id"]).json()
        pinned = {
            **config,
            "positions": source["observations"],
            "epoch_utc": source["epoch_utc"],
            "position_source": {"simulation_id": simulation["id"], "output_sha256": source["output_sha256"]},
        }
        assert client.post("/api/telemetry/configuration/validate", json=pinned).status_code == 200
        pinned["position_source"]["output_sha256"] = "0" * 64
        assert client.post("/api/telemetry/studies", json=pinned).status_code == 422
        archive_sim = client.post("/api/telemetry/archives", json={"simulation_id": simulation["id"]})
        assert archive_sim.status_code == 201, archive_sim.text
    with TestClient(create_app(tmp_path, seed=False)) as restarted:
        assert restarted.get("/api/telemetry/studies/" + ident).json() == evidence
        assert restarted.get("/api/telemetry/archives/" + archive_id + "/binary").content == raw


def test_short_contact_between_ticks_is_used_and_stale_fix_is_not_retimestamped():
    values = example_study().model_dump()
    values["duration_s"] = 180
    values["outages"] = []
    values["contacts"] = [dict(values["contacts"][0], start_s=1.1, end_s=1.8, loss_probability=0)]
    result = simulate_recovery(RecoveryRequest.model_validate(values))
    assert len(result["events"]) == 1 and result["events"][0]["time_s"] == 1.1
    values["contacts"][0].update(start_s=0, end_s=180)
    values["positions"] = [values["positions"][i] for i in (0, 2)]
    values["fresh_interval_s"] = 60
    result = simulate_recovery(RecoveryRequest.model_validate(values))
    assert not result["records"][1]["fix_valid"]
    fresh = [e for e in result["events"] if e["decision"] == "fresh_position_due" and e["time_s"] == 60][0]
    assert decode(bytes.fromhex(fresh["packet_hex"]))["observations"][0]["time_s"] == 0
    assert result["freshness"]["max_known_position_age_s"] >= 60


def test_us915_channel_mask_hopping_and_rolling_airtime():
    values = example_study().model_dump()
    values.update(duration_s=180, fresh_interval_s=10, step_s=1, fair_use_s_per_24h=None, outages=[])
    values["profiles"][0].update(region="US915", duty_fraction=1)
    values["contacts"] = [
        dict(
            values["contacts"][0],
            start_s=0,
            end_s=180,
            region="US915",
            data_rates=[0],
            channels_hz=[902300000],
            loss_probability=0,
        )
    ]
    result = simulate_recovery(RecoveryRequest.model_validate(values))
    assert len(result["events"]) > 1
    for event in result["events"]:
        assert event["frequency_hz"] == 902300000
        end = event["end_s"]
        occupancy = sum(
            max(0, min(e["end_s"], end) - max(e["time_s"], end - 20))
            for e in result["events"]
            if e["time_s"] < end
        )
        assert occupancy <= 0.4 + 1e-10
    values["contacts"][0]["channels_hz"] = [868100000]
    with pytest.raises(ValidationError, match="channel mask"):
        RecoveryRequest.model_validate(values)


def test_power_harvesting_spillage_and_receiver_loss_are_separate():
    values = example_study().model_dump()
    values["power"].update(harvest_w=2, battery_initial_j=1200)
    result = simulate_recovery(RecoveryRequest.model_validate(values))
    assert result["metrics"]["spilled_j"] > 0
    assert abs(result["metrics"]["energy_balance_residual_j"]) < 1e-7
    values["fair_use_s_per_24h"] = 0.001
    assert simulate_recovery(RecoveryRequest.model_validate(values))["events"] == []


def test_archive_context_and_clock_discontinuities_are_preserved():
    from packages.telemetry.archive import archive_context

    rows = [
        observation().model_copy(update={"time_s": t, "clock_valid": valid})
        for t, valid in [(60, True), (0, False), (70, True)]
    ]
    raw = encode_archive(rows, "2026-10-28T00:00:00+00:00")
    assert archive_context(raw)["epoch_utc"] == "2026-10-28T00:00:00+00:00"
    assert canonical_records(decode_archive(raw)) == canonical_records(rows)
    assert "clock_discontinuity" in scientific_summary(rows)["records"][1]["reasons"]
    damaged = bytearray(raw)
    damaged[76] ^= 1
    with pytest.raises(ValueError, match="context SHA"):
        decode_archive(bytes(damaged))


def test_telemetry_evidence_backup_restore_and_corruption_guard(tmp_path):
    from packages.telemetry.evidence import verify_evidence
    from scripts.backup import backup
    from scripts.verify_backup import restore_backup
    from services.api.storage import Record

    app = create_app(tmp_path)
    with TestClient(app) as c:
        run_one(app.state.sessions, tmp_path)
        config = c.get("/api/telemetry/example").json()
        job = c.post("/api/telemetry/studies", json=config).json()
        run_one(app.state.sessions, tmp_path)
        ident = c.get("/api/jobs/" + job["id"]).json()["result_id"]
        evidence = c.get("/api/telemetry/studies/" + ident).json()
        archive = c.post(
            "/api/telemetry/archives",
            json={"observations": config["positions"], "epoch_utc": config["epoch_utc"]},
        ).json()
        assert archive["id"] in [r["id"] for r in c.get("/api/telemetry/archives").json()]
        destination = tmp_path.parent / (tmp_path.name + "-backup")
        backup(tmp_path, destination)
        restored = tmp_path.parent / (tmp_path.name + "-restored")
        restore_backup(destination, restored)
        with TestClient(create_app(restored, seed=False)) as rc:
            assert rc.get("/api/telemetry/studies/" + ident).json() == evidence
            assert rc.get("/api/telemetry/archives/" + archive["id"]).json() == archive
        with app.state.sessions() as session:
            row = session.get(Record, ident)
            damaged = copy.deepcopy(row.payload)
            damaged["output"]["metrics"]["received_records"] += 1
            row.payload = damaged
            session.commit()
        assert c.get("/api/telemetry/studies/" + ident).status_code == 409
        with pytest.raises(ValueError):
            verify_evidence(damaged, ident, "telemetry_study")
        with pytest.raises(ValueError):
            backup(tmp_path, tmp_path.parent / (tmp_path.name + "-corrupt"))


def test_airtime_reservation_prevents_history_starving_fresh_tracking():
    values = example_study().model_dump()
    values.update(duration_s=14400, fair_use_s_per_24h=6)
    values["profiles"][0]["end_s"] = 14400
    values["contacts"] = [dict(values["contacts"][0], start_s=0, end_s=14400)]
    values["positions"] = [
        Observation(
            time_s=t, sequence=i, latitude_deg=45, longitude_deg=9.7, altitude_m=12500, origin="simulated"
        ).model_dump()
        for i, t in enumerate(range(0, 14401, 60))
    ]
    values["outages"] = []
    result = simulate_recovery(RecoveryRequest.model_validate(values))
    assert result["metrics"]["airtime_s"] <= 6 + 1e-9
    assert result["freshness"]["max_known_position_age_s"] < 1800
    assert any(e["family"] == "HISTORY" for e in result["events"])
