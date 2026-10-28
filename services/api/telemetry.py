"""Local protocol tools and durable recovery studies; no actual transmitter."""

import hashlib
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from packages.domain.models import digest, utcnow
from packages.telemetry.archive import (
    archive_context,
    canonical_records,
    decode_archive,
    encode_archive,
    scientific_summary,
)
from packages.telemetry.codec import decode, encode
from packages.telemetry.evidence import verify_evidence
from packages.telemetry.examples import example_study
from packages.telemetry.models import (
    ArchiveRequest,
    BatchRequest,
    CodecRequest,
    DecodeRequest,
    Observation,
    RadioRequest,
    RecoveryRequest,
)
from packages.telemetry.radio import TABLES, optimize_batch, validate_radio
from services.api.provenance import assert_runtime_unchanged
from services.api.storage import Record


def register_telemetry(app: FastAPI, factory, enqueue, record, runtime):
    def checked(fn, *args):
        try:
            assert_runtime_unchanged(runtime)
            result = fn(*args)
            assert_runtime_unchanged(runtime)
            return result
        except (ValueError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc

    def evidence(ident, kind):
        result = record(str(ident), kind)
        try:
            verify_evidence(result, str(ident), kind)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return result

    @app.get("/api/telemetry/profiles")
    def profiles():
        return {
            "wire_version": 1,
            "tables": TABLES,
            "revision": "RP002-1.0.3",
            "transmitter": False,
            "family_bytes": {"NAV": 19, "NAV+ENV": 24, "HISTORY": "variable", "EMERGENCY": 11},
        }

    @app.get("/api/telemetry/example")
    def example():
        return example_study().model_dump(mode="json")

    @app.post("/api/telemetry/codec/encode")
    def encode_packet(request: CodecRequest):
        raw = checked(encode, request.family, request.observations)
        return {"hex": raw.hex(), "sha256": hashlib.sha256(raw).hexdigest(), **checked(decode, raw)}

    @app.post("/api/telemetry/codec/decode")
    def decode_packet(request: DecodeRequest):
        return checked(lambda: decode(bytes.fromhex(request.hex)))

    @app.post("/api/telemetry/radio/validate")
    def validate(request: RadioRequest):
        return checked(validate_radio, request)

    @app.post("/api/telemetry/batches/optimize")
    def batching(request: BatchRequest):
        return checked(optimize_batch, request)

    def validate_position_source(request):
        if request.position_source:
            original = source(request.position_source.simulation_id)
            if (
                original["output_sha256"] != request.position_source.output_sha256
                or digest(original["observations"]) != digest([p.model_dump() for p in request.positions])
                or request.epoch_utc.isoformat() != original["epoch_utc"].replace("Z", "+00:00")
            ):
                raise HTTPException(
                    422,
                    "Pinned position source/hash/epoch differs; load its exact observations or explicitly clear position_source for edited data",
                )

    @app.post("/api/telemetry/configuration/validate")
    def validate_configuration(request: RecoveryRequest):
        validate_position_source(request)
        return request.model_dump(mode="json")

    @app.post("/api/telemetry/studies", status_code=202)
    def submit(request: RecoveryRequest):
        checked(lambda: None)
        validate_position_source(request)
        return enqueue("telemetry_recovery", request.model_dump(mode="json"))

    @app.get("/api/telemetry/studies")
    def studies():
        with factory() as session:
            values = list(
                session.scalars(
                    select(Record)
                    .where(Record.kind == "telemetry_study")
                    .order_by(Record.created_utc.desc())
                    .limit(50)
                )
            )
            return [
                {
                    "id": v.id,
                    "created_utc": v.payload["created_utc"],
                    "metrics": v.payload["output"]["metrics"],
                }
                for v in values
            ]

    @app.get("/api/telemetry/studies/{ident}")
    def study(ident: UUID):
        return evidence(ident, "telemetry_study")

    @app.get("/api/telemetry/sources/{ident}")
    def source(ident: UUID):
        result = record(str(ident), "simulation")
        records = [
            Observation(
                time_s=round(s["elapsed_s"]),
                sequence=i % 65536,
                latitude_deg=s["latitude_deg"],
                longitude_deg=s["longitude_deg"],
                altitude_m=s["geometric_msl_m"],
                temperature_k=s["temperature_k"],
                pressure_pa=s["pressure_pa"],
                origin="simulated",
            )
            for i, s in enumerate(result["samples"])
        ]
        return {
            "simulation_id": str(ident),
            "output_sha256": result["manifest"]["output_sha256"],
            "epoch_utc": result["manifest"]["config"]["launch"]["start_utc"],
            "observations": [r.model_dump() for r in records],
        }

    @app.post("/api/telemetry/archives", status_code=201)
    def archive(request: ArchiveRequest):
        rows = request.observations
        source_metadata = None
        if request.simulation_id:
            source_metadata = source(request.simulation_id)
            rows = [Observation.model_validate(r) for r in source_metadata["observations"]]
        epoch = (
            source_metadata["epoch_utc"]
            if source_metadata
            else (request.epoch_utc.isoformat() if request.epoch_utc else None)
        )
        raw = checked(encode_archive, rows, epoch)
        restored = checked(decode_archive, raw)
        if restored != rows:
            raise HTTPException(409, "Archive round-trip mismatch")
        # A difficult/invalid summary must never discard an otherwise verified lossless archive.
        try:
            summary = checked(scientific_summary, rows, request.trajectory_tolerance_m)
        except HTTPException as exc:
            summary = {
                "kind": "summary_unavailable",
                "original_count": len(rows),
                "retained_count": 0,
                "records": [],
                "limitations": str(exc.detail),
            }
        ident = str(uuid4())
        result = {
            "id": ident,
            "kind": "telemetry_archive",
            "created_utc": utcnow().isoformat(),
            "schema_version": 1,
            "configuration": request.model_dump(mode="json"),
            "code": runtime,
            "source_simulation": {k: v for k, v in source_metadata.items() if k != "observations"}
            if source_metadata
            else None,
            "source_sha256": hashlib.sha256(canonical_records(rows)).hexdigest(),
            "archive_sha256": hashlib.sha256(raw).hexdigest(),
            "archive_hex": raw.hex(),
            "original_bytes": len(canonical_records(rows)),
            "archive_bytes": len(raw),
            "record_count": len(rows),
            "round_trip_verified": True,
            "summary": summary,
        }
        result["sha256"] = digest(result)
        with factory() as session:
            session.add(Record(id=ident, kind="telemetry_archive", payload=result))
            session.commit()
        return result

    @app.get("/api/telemetry/archives")
    def archive_list():
        with factory() as session:
            values = session.scalars(
                select(Record)
                .where(Record.kind == "telemetry_archive")
                .order_by(Record.created_utc.desc())
                .limit(50)
            )
            return [
                {
                    "id": v.id,
                    "created_utc": v.payload["created_utc"],
                    "record_count": v.payload["record_count"],
                }
                for v in values
            ]

    @app.get("/api/telemetry/archives/{ident}")
    def get_archive(ident: UUID):
        return evidence(ident, "telemetry_archive")

    @app.get("/api/telemetry/archives/{ident}/binary")
    def binary(ident: UUID):
        result = evidence(ident, "telemetry_archive")
        return Response(
            bytes.fromhex(result["archive_hex"]),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="stratos-{ident}.stla"'},
        )

    @app.post("/api/telemetry/archives/decode")
    async def restore(request: Request):
        raw = await request.body()
        return {
            "observations": [r.model_dump() for r in checked(decode_archive, raw)],
            "lossless_verified": True,
            "context": checked(archive_context, raw),
        }
