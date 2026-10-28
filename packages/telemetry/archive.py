"""Lossless typed-observation archive, separate from radio quantization and lossy summaries."""

import hashlib
import json
import struct
import zlib

from geographiclib.geodesic import Geodesic

from packages.telemetry.codec import read_varint, varint
from packages.telemetry.models import Observation

MAGIC = b"STLA\x01"
MAX_BYTES = 4 * 1024 * 1024


def canonical_records(records: list[Observation]) -> bytes:
    return json.dumps(
        [r.model_dump() for r in records], sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def encode_archive(records: list[Observation], epoch_utc: str | None = None) -> bytes:
    if not 1 <= len(records) <= 5000:
        raise ValueError("Archive requires1–5000 observations")
    original = canonical_records(records)
    result = bytearray(MAGIC + struct.pack(">I", len(records)) + hashlib.sha256(original).digest())
    context = json.dumps({"epoch_utc": epoch_utc}, sort_keys=True, separators=(",", ":")).encode()
    result += struct.pack(">H", len(context)) + hashlib.sha256(context).digest() + context
    for start in range(0, len(records), 64):
        block = bytearray()
        previous = b""
        subset = records[start : start + 64]
        for record in subset:
            row = json.dumps(
                record.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
            prefix = 0
            while prefix < min(len(row), len(previous)) and row[prefix] == previous[prefix]:
                prefix += 1
            suffix = row[prefix:]
            block += varint(prefix) + varint(len(suffix)) + suffix
            previous = row
        packed = zlib.compress(bytes(block), level=9)
        result += struct.pack(">HIII", len(subset), len(block), len(packed), zlib.crc32(block)) + packed
    return bytes(result)


def decode_archive(data: bytes) -> list[Observation]:
    if len(data) > MAX_BYTES or len(data) < 75 or data[:5] != MAGIC:
        raise ValueError("Archive magic/version/size invalid")
    count = int.from_bytes(data[5:9], "big")
    if not 1 <= count <= 5000:
        raise ValueError("Archive record count invalid")
    result: list[Observation] = []
    context = archive_context(data)
    del context
    expected, offset, expanded = data[9:41], 75 + int.from_bytes(data[41:43], "big"), 0
    while len(result) < count:
        if offset + 14 > len(data):
            raise ValueError("Truncated archive block header")
        n, raw_size, packed_size, crc = struct.unpack(">HIII", data[offset : offset + 14])
        offset += 14
        expanded += raw_size
        if (
            not 1 <= n <= 64
            or len(result) + n > count
            or expanded > MAX_BYTES
            or offset + packed_size > len(data)
        ):
            raise ValueError("Invalid/excessive archive block lengths")
        decoder = zlib.decompressobj()
        try:
            block = decoder.decompress(data[offset : offset + packed_size], raw_size + 1)
        except zlib.error as exc:
            raise ValueError("Corrupt archive compression") from exc
        if len(block) != raw_size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("Archive expanded length/stream mismatch")
        if zlib.crc32(block) != crc:
            raise ValueError("Archive block CRC mismatch")
        cursor, previous = 0, b""
        for _ in range(n):
            prefix, cursor = read_varint(block, cursor)
            size, cursor = read_varint(block, cursor)
            if prefix > len(previous) or cursor + size > len(block):
                raise ValueError("Invalid archive delta")
            row = previous[:prefix] + block[cursor : cursor + size]
            cursor += size
            try:
                result.append(Observation.model_validate(json.loads(row)))
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid archived observation") from exc
            previous = row
        if cursor != len(block):
            raise ValueError("Archive block has trailing data")
        offset += packed_size
    if offset != len(data) or hashlib.sha256(canonical_records(result)).digest() != expected:
        raise ValueError("Archive source SHA-256/trailing bytes mismatch")
    return result


def scientific_summary(records: list[Observation], tolerance_m: float = 100) -> dict:
    if not records:
        raise ValueError("Summary requires observations")
    retained: dict[int, set[str]] = {0: {"endpoint"}, len(records) - 1: {"endpoint"}}

    def keep(i, reason):
        retained.setdefault(i, set()).add(reason)

    for field in ("altitude_m", "temperature_k", "voltage_v", "pressure_pa"):
        scalar_valid = [
            (i, getattr(r, field)) for i, r in enumerate(records) if getattr(r, field) is not None
        ]
        if scalar_valid:
            keep(min(scalar_valid, key=lambda v: v[1])[0], field + "_minimum")
            keep(max(scalar_valid, key=lambda v: v[1])[0], field + "_maximum")
        for i in range(1, len(records)):
            if (getattr(records[i - 1], field) is None) != (getattr(records[i], field) is None):
                keep(i - 1, "validity_transition")
                keep(i, "validity_transition")
    for i in range(1, len(records)):
        if records[i].time_s <= records[i - 1].time_s:
            keep(i - 1, "clock_discontinuity")
            keep(i, "clock_discontinuity")
        if (records[i].fix_valid, records[i].clock_valid, records[i].latitude_deg is None) != (
            records[i - 1].fix_valid,
            records[i - 1].clock_valid,
            records[i - 1].latitude_deg is None,
        ):
            keep(i - 1, "validity_transition")
            keep(i, "validity_transition")
    # Time-parametrized WGS84 interpolation error; retain significant bends AND speed changes.
    valid = [i for i, r in enumerate(records) if r.fix_valid and r.clock_valid and r.latitude_deg is not None]
    segments: list[list[int]] = []
    for i in valid:
        if not segments or i != segments[-1][-1] + 1 or records[i].time_s <= records[segments[-1][-1]].time_s:
            segments.append([i])
        else:
            segments[-1].append(i)
    evaluations = 0
    for segment in segments:
        keep(segment[0], "valid_segment_endpoint")
        keep(segment[-1], "valid_segment_endpoint")
        pending = [(segment[0], segment[-1])]
        while pending:
            a, b = pending.pop()
            if b <= a + 1:
                continue
            x, y = records[a], records[b]
            line = Geodesic.WGS84.InverseLine(
                x.latitude_deg, x.longitude_deg, y.latitude_deg, y.longitude_deg
            )
            worst, selected = tolerance_m, None
            for i in range(a + 1, b):
                evaluations += 1
                if evaluations > 100000:
                    raise ValueError(
                        "Summary exceeds100000 geodesic evaluations; split input or increase tolerance"
                    )
                row = records[i]
                p = line.Position(line.s13 * (row.time_s - x.time_s) / (y.time_s - x.time_s))
                error = Geodesic.WGS84.Inverse(row.latitude_deg, row.longitude_deg, p["lat2"], p["lon2"])[
                    "s12"
                ]
                if error > worst:
                    worst, selected = error, i
            if selected is not None:
                keep(selected, "trajectory_change")
                pending.extend(((a, selected), (selected, b)))
    return {
        "kind": "lossy_scientific_summary",
        "original_count": len(records),
        "retained_count": len(retained),
        "trajectory_tolerance_m": tolerance_m,
        "limitations": "Retains global scalar extrema, validity transitions and time-parametrized path changes; intermediate scalar behavior may be lost. Original archive remains authoritative.",
        "records": [
            {"index": i, "reasons": sorted(retained[i]), "observation": records[i].model_dump()}
            for i in sorted(retained)
        ],
    }


def archive_context(data: bytes) -> dict:
    if len(data) < 75 or data[:5] != MAGIC:
        raise ValueError("Archive context header missing")
    size = int.from_bytes(data[41:43], "big")
    if size > 1024 or 75 + size > len(data):
        raise ValueError("Archive context size invalid")
    raw = data[75 : 75 + size]
    if hashlib.sha256(raw).digest() != data[43:75]:
        raise ValueError("Archive context SHA-256 mismatch")
    try:
        context = json.loads(raw)
    except ValueError as exc:
        raise ValueError("Invalid archive context JSON") from exc
    if (
        not isinstance(context, dict)
        or set(context) != {"epoch_utc"}
        or not isinstance(context["epoch_utc"], (str, type(None)))
    ):
        raise ValueError("Unsupported archive context")
    return context
