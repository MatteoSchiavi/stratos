"""STRATOS wire v1; big endian; CRC-16/CCITT-FALSE except MIC-only emergency."""

import binascii
import math
import struct

from packages.telemetry.models import Observation

VERSION = 1
FAMILIES = {"NAV": 0, "NAV+ENV": 1, "HISTORY": 2, "EMERGENCY": 3}
COORD_MAX = (1 << 24) - 2
MISSING_COORD = COORD_MAX + 1


def u24(value: int) -> bytes:
    return value.to_bytes(3, "big")


def varint(value: int) -> bytes:
    if value < 0 or value > (1 << 64) - 1:
        raise ValueError("Varint exceeds unsigned64 range")
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    start = offset
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("Truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            if value > (1 << 64) - 1 or data[start:offset] != varint(value):
                raise ValueError("Noncanonical/overflow varint")
            return value, offset
    raise ValueError("Overflow varint")


def zigzag(value: int) -> int:
    return value * 2 if value >= 0 else -value * 2 - 1


def unzigzag(value: int) -> int:
    return -(value // 2) - 1 if value & 1 else value // 2


def quantize_coordinate(value: float, latitude: bool) -> int:
    span = 180 if latitude else 360
    bound = span / 2
    if not math.isfinite(value) or not -bound <= value <= bound:
        raise ValueError("Coordinate outside global range")
    return round((value + bound) * COORD_MAX / span)


def values(obs: Observation) -> list[int]:
    position = obs.fix_valid and obs.latitude_deg is not None
    latitude = obs.latitude_deg if obs.latitude_deg is not None else 0.0
    longitude = obs.longitude_deg if obs.longitude_deg is not None else 0.0
    flags = int(position) | (int(obs.clock_valid) << 1)
    flags |= 4 if obs.altitude_m is not None else 0
    flags |= 8 if obs.voltage_v is not None else 0
    flags |= 16 if obs.temperature_k is not None else 0
    flags |= 32 if obs.pressure_pa is not None else 0
    return [
        obs.time_s,
        obs.sequence,
        flags,
        quantize_coordinate(latitude, True) if position else MISSING_COORD,
        quantize_coordinate(longitude, False) if position else MISSING_COORD,
        round(obs.altitude_m) if obs.altitude_m is not None else -32768,
        round(obs.voltage_v * 1000) if obs.voltage_v is not None else 65535,
        round((obs.temperature_k - 273.15) * 100) if obs.temperature_k is not None else -32768,
        round(obs.pressure_pa) if obs.pressure_pa is not None else MISSING_COORD,
    ]


def observation(row: list[int]) -> dict:
    t, seq, flags, lat, lon, alt, volt, temp, pressure = row
    if not 0 <= flags <= 63 or not 0 <= t <= 16777215 or not 0 <= seq <= 65535:
        raise ValueError("Invalid flags/time/sequence")
    for bit, v, missing, low, high in (
        (1, lat, MISSING_COORD, 0, COORD_MAX),
        (1, lon, MISSING_COORD, 0, COORD_MAX),
        (4, alt, -32768, -32767, 32767),
        (8, volt, 65535, 0, 65534),
        (16, temp, -32768, -27315, 22685),
        (32, pressure, MISSING_COORD, 0, COORD_MAX),
    ):
        if (flags & bit and not low <= v <= high) or (not flags & bit and v != missing):
            raise ValueError("Validity flag and field/sentinel disagree")
    return {
        "time_s": t,
        "sequence": seq,
        "flags": flags,
        "clock_valid": bool(flags & 2),
        "fix_valid": bool(flags & 1),
        "latitude_deg": lat * 180 / COORD_MAX - 90 if flags & 1 else None,
        "longitude_deg": lon * 360 / COORD_MAX - 180 if flags & 1 else None,
        "altitude_m": alt if flags & 4 else None,
        "voltage_v": volt / 1000 if flags & 8 else None,
        "temperature_k": temp / 100 + 273.15 if flags & 16 else None,
        "pressure_pa": pressure if flags & 32 else None,
    }


def encode(family: str, observations: list[Observation]) -> bytes:
    if family not in FAMILIES or not observations or len(observations) > 32:
        raise ValueError("Unsupported family or record count")
    if family != "HISTORY" and len(observations) != 1:
        raise ValueError("Only HISTORY can group observations")
    header = bytes([16 | FAMILIES[family]])
    row = values(observations[0])
    t, seq, flags, lat, lon, alt, volt, temp, pressure = row
    if family == "EMERGENCY":
        if t // 60 > 65535:
            raise ValueError(
                "EMERGENCY exceeds65535 mission-relative minutes; select a new explicit session epoch"
            )
        return header + bytes([flags & 3, seq % 256]) + struct.pack(">H", t // 60) + u24(lat) + u24(lon)
    if family == "HISTORY":
        if any(a.time_s >= b.time_s for a, b in zip(observations, observations[1:], strict=False)):
            raise ValueError("HISTORY requires strictly increasing times")
        body = header + bytes([len(observations)])
        previous = [0] * 9
        for obs in observations:
            current = values(obs)
            body += b"".join(varint(zigzag(a - b)) for a, b in zip(current, previous, strict=False))
            previous = current
    else:
        body = header + bytes([flags if family == "NAV+ENV" else flags & 15])
        body += struct.pack(">H", seq) + u24(t) + u24(lat) + u24(lon) + struct.pack(">hH", alt, volt)
        if family == "NAV+ENV":
            body += struct.pack(">h", temp) + u24(pressure)
    return body + struct.pack(">H", binascii.crc_hqx(body, 0xFFFF))


def decode(data: bytes) -> dict:
    if not data or data[0] >> 4 != VERSION or data[0] & 12:
        raise ValueError("Unsupported protocol version/reserved header bits")
    family = list(FAMILIES)[data[0] & 3]
    exact = {"NAV": 19, "NAV+ENV": 24, "EMERGENCY": 11}
    if family in exact and len(data) != exact[family]:
        raise ValueError("Incorrect packet length")
    if family != "EMERGENCY":
        if len(data) < 4 or binascii.crc_hqx(data[:-2], 0xFFFF) != int.from_bytes(data[-2:], "big"):
            raise ValueError("CRC-16 mismatch/truncated packet")

    def n(start, end):
        return int.from_bytes(data[start:end], "big")

    if family == "EMERGENCY":
        rows = [[n(3, 5) * 60, data[2], data[1], n(5, 8), n(8, 11), -32768, 65535, -32768, MISSING_COORD]]
    elif family == "HISTORY":
        if not 1 <= data[1] <= 32:
            raise ValueError("Invalid history count")
        rows, previous, offset = [], [0] * 9, 2
        for _ in range(data[1]):
            current = []
            for old in previous:
                v, offset = read_varint(data[:-2], offset)
                current.append(old + unzigzag(v))
            observation(current)
            rows.append(current)
            previous = current
        if offset != len(data) - 2 or any(a[0] >= b[0] for a, b in zip(rows, rows[1:], strict=False)):
            raise ValueError("Trailing history bytes/nonmonotonic history")
    else:
        alt, volt = struct.unpack(">hH", data[13:17])
        temp, pressure = (
            (-32768, MISSING_COORD) if family == "NAV" else (struct.unpack(">h", data[17:19])[0], n(19, 22))
        )
        rows = [[n(4, 7), n(2, 4), data[1], n(7, 10), n(10, 13), alt, volt, temp, pressure]]
    return {
        "version": VERSION,
        "family": family,
        "bytes": len(data),
        "integrity": "external_LoRaWAN_MIC_required"
        if family == "EMERGENCY"
        else "CRC16_verified_not_authentication",
        "sequence_bits": 8 if family == "EMERGENCY" else 16,
        "time_resolution_s": 60 if family == "EMERGENCY" else 1,
        "epoch": "explicit mission/session UTC epoch required out of band; never infer rollover",
        "observations": [observation(r) for r in rows],
    }
