import csv
import io
import json
from contextlib import asynccontextmanager
from datetime import UTC
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from packages.domain.integrity import verify_simulation
from packages.domain.models import (
    ComparisonRequest,
    DownloadRequest,
    ExploreRequest,
    MissionConfig,
    SimulationRequest,
    digest,
    utcnow,
)
from packages.flight.comparison import compare_runs
from packages.flight.geojson import geometry
from packages.meteo.explorer import SliceCache, explore
from packages.meteo.field import WeatherDomainError
from packages.meteo.gfs import LEVELS_HPA, estimate_download, list_available_runs
from services.api.provenance import assert_runtime_unchanged, code_identity
from services.api.storage import DATA, ROOT, Job, Record, make_engine, migrate

API_RUNTIME_CODE = code_identity()


def job_dict(job: Job):
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result_id": job.result_id,
        "cancel_requested": job.cancel_requested,
        "created_utc": job.created_utc.replace(tzinfo=UTC).isoformat(),
        "updated_utc": job.updated_utc.replace(tzinfo=UTC).isoformat(),
    }


def save_revision(session, config: MissionConfig):
    mission_id = str(config.id)
    existing = session.get(Record, mission_id)
    if existing and existing.kind != "mission":
        raise HTTPException(409, "ID belongs to a different record type")
    revision_id = str(uuid4())
    revision = {
        "id": revision_id,
        "mission_id": mission_id,
        "schema_version": 1,
        "config_sha256": config.revision_hash,
        "config": config.model_dump(mode="json"),
        "created_utc": utcnow().isoformat(),
        "origin": config.origin,
        "calibration_status": "uncalibrated",
    }
    session.add(Record(id=revision_id, kind="revision", payload=revision))
    payload = {
        "id": mission_id,
        "name": config.name,
        "latest_revision_id": revision_id,
        "operating_mode": config.operating_mode,
        "updated_utc": revision["created_utc"],
    }
    if existing:
        existing.payload = payload
    else:
        session.add(Record(id=mission_id, kind="mission", payload=payload))
    session.commit()
    return revision


def create_app(data: Path = DATA, seed: bool = True) -> FastAPI:
    engine = make_engine(data)
    factory = sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        migrate(engine)
        if seed:
            from services.api.reference_data import register_reference

            register_reference(factory, data)
            with factory() as session:
                if not session.scalar(select(Record).where(Record.kind == "mission").limit(1)):
                    config = MissionConfig.model_validate(yaml.safe_load((ROOT / "mission.yaml").read_text()))
                    revision = save_revision(session, config)
                    session.add(
                        Job(id=str(uuid4()), kind="simulation", payload={"revision_id": revision["id"]})
                    )
                    session.commit()
        yield
        engine.dispose()

    app = FastAPI(title="STRATOS Mission Engineering", version="0.1.0", lifespan=lifespan)
    app.state.sessions = factory
    slices = SliceCache()

    @app.middleware("http")
    async def local_write_guard(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if (origin and urlsplit(origin).netloc != request.headers.get("host")) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return JSONResponse(
                    {"detail": "Cross-origin writes are disabled for this local application"}, status_code=403
                )
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 64 * 1024:
                    return JSONResponse({"detail": "Request exceeds 64 KiB limit"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def record(record_id: str, kind: str) -> dict:
        with factory() as session:
            value = session.get(Record, record_id)
            if not value or value.kind != kind:
                raise HTTPException(404, f"{kind} not found")
            payload = value.payload
            if kind == "simulation":
                try:
                    verify_simulation(payload, record_id)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
            return payload

    def records(kind: str):
        with factory() as session:
            return [
                r.payload
                for r in session.scalars(
                    select(Record).where(Record.kind == kind).order_by(Record.created_utc.desc()).limit(100)
                )
            ]

    def enqueue(kind: str, payload: dict):
        with factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            active = session.scalar(
                select(func.count()).select_from(Job).where(Job.status.in_(["queued", "running"]))
            )
            if (active or 0) >= 8:
                raise HTTPException(429, "Queue limit of 8 active jobs reached")
            job = Job(id=str(uuid4()), kind=kind, payload=payload)
            session.add(job)
            session.commit()
            return job_dict(job)

    @app.get("/api/health")
    def health():
        with factory() as session:
            session.execute(select(1))
            heartbeat = session.get(Record, "runtime_worker")
            from datetime import datetime

            heartbeat_age = (
                (utcnow() - datetime.fromisoformat(heartbeat.payload["heartbeat_utc"])).total_seconds()
                if heartbeat
                else None
            )
        return {
            "status": "ok",
            "schema_version": 1,
            "database": "SQLite WAL",
            "time_utc": utcnow().isoformat(),
            "scope": "P0/P1",
            "no_launch_authority": True,
            "worker": {
                "state": (
                    "unavailable"
                    if heartbeat_age is None or not 0 <= heartbeat_age < 15
                    else "restart_required"
                    if heartbeat and heartbeat.payload.get("code_changed")
                    else "ready"
                ),
                "heartbeat_age_s": heartbeat_age,
            },
        }

    @app.get("/api/providers/weather")
    def providers():
        return [
            {"id": "SYNTHETIC", "quality": "hypothetical", "offline": True},
            {
                "id": "NOAA_GFS",
                "quality": "forecast_not_observation",
                "grid_deg": 0.25,
                "member": "deterministic",
                "source_uri": "https://nomads.ncep.noaa.gov",
                "max_lead_hours": 120,
                "max_window_hours": 72,
                "pressure_levels_pa": [p * 100 for p in LEVELS_HPA],
            },
        ]

    @app.get("/api/missions")
    def missions():
        return records("mission")

    @app.post("/api/missions", status_code=201)
    def new_mission(config: MissionConfig):
        with factory() as session:
            return save_revision(session, config)

    @app.get("/api/missions/{mission_id}")
    def get_mission(mission_id: UUID):
        return record(str(mission_id), "mission")

    @app.post("/api/missions/{mission_id}/revisions", status_code=201)
    def new_revision(mission_id: UUID, config: MissionConfig):
        record(str(mission_id), "mission")
        if config.id != mission_id:
            raise HTTPException(422, "Mission ID must match the mission being revised")
        with factory() as session:
            return save_revision(session, config)

    @app.get("/api/revisions/{revision_id}")
    def get_revision(revision_id: UUID):
        return record(str(revision_id), "revision")

    @app.get("/api/revisions/{revision_id}/yaml")
    def export_yaml(revision_id: UUID):
        revision = record(str(revision_id), "revision")
        return Response(
            yaml.safe_dump(revision["config"], sort_keys=False),
            media_type="application/yaml",
            headers={"Content-Disposition": 'attachment; filename="mission.yaml"'},
        )

    @app.post("/api/missions/import-yaml", status_code=201)
    async def import_yaml(request: Request):
        try:
            raw = yaml.safe_load(await request.body())
            config = MissionConfig.model_validate(raw)
        except (yaml.YAMLError, ValidationError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        with factory() as session:
            return save_revision(session, config)

    @app.get("/api/weather/runs")
    def weather_runs():
        try:
            return list_available_runs()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                502,
                f"NOAA discovery unavailable ({type(exc).__name__}). Check network access to nomads.ncep.noaa.gov; select a cached dataset or explicit synthetic demo.",
            ) from exc

    @app.post("/api/weather/estimate")
    def estimate(config: DownloadRequest):
        return estimate_download(config)

    @app.post("/api/weather/downloads", status_code=202)
    def download(config: DownloadRequest):
        estimate = estimate_download(config)
        if estimate["unpacked_array_bytes"] > estimate["memory_limit_bytes"]:
            raise HTTPException(422, "Decoded weather exceeds memory limit; reduce ROI or duration")
        return enqueue("weather", config.model_dump(mode="json"))

    @app.get("/api/weather/datasets")
    def datasets():
        return records("dataset")

    @app.post("/api/weather/explore")
    def inspect_weather(config: ExploreRequest):
        dataset = record(config.dataset_id, "dataset")
        try:
            field = slices.get(data / "cache" / config.dataset_id, config.time_utc)
            if field.provenance.get("sha256") != dataset.get("sha256"):
                raise ValueError("Registered forecast identity differs from cached manifest")
            assert_runtime_unchanged(API_RUNTIME_CODE)
            result = explore(field, config)
            assert_runtime_unchanged(API_RUNTIME_CODE)
            result["code"] = {
                **API_RUNTIME_CODE,
                "identity_scope": "API startup snapshot; scientific source/dependencies checked before and after inspection",
            }
            result["inspection_sha256"] = digest(
                {k: v for k, v in result.items() if k != "inspection_sha256"}
            )
            return result
        except (WeatherDomainError, ValueError, FileNotFoundError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/summary")
    def summary():
        with factory() as session:
            counts = dict(session.execute(select(Record.kind, func.count()).group_by(Record.kind)).all())
        return {
            "missions": counts.get("mission", 0),
            "simulations": counts.get("simulation", 0),
            "datasets": counts.get("dataset", 0),
        }

    @app.get("/api/jobs")
    def jobs():
        with factory() as session:
            return [
                job_dict(job)
                for job in session.scalars(select(Job).order_by(Job.created_utc.desc()).limit(30))
            ]

    @app.get("/api/jobs/{job_id}")
    @app.get("/api/weather/downloads/{job_id}")
    def get_job(job_id: UUID):
        with factory() as session:
            job = session.get(Job, str(job_id))
            if not job:
                raise HTTPException(404, "Job not found")
            return job_dict(job)

    @app.post("/api/jobs/{job_id}/cancel")
    @app.post("/api/simulations/{job_id}/cancel")
    def cancel(job_id: UUID):
        with factory() as session:
            job = session.get(Job, str(job_id))
            if not job:
                raise HTTPException(404, "Job not found")
            if job.status in ("queued", "running"):
                job.cancel_requested = True
                if job.status == "queued":
                    job.status, job.message = "cancelled", "Cancelled before execution"
                job.updated_utc = utcnow()
                session.commit()
            return job_dict(job)

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: UUID):
        with factory() as session:
            old = session.get(Job, str(job_id))
            if not old:
                raise HTTPException(404, "Job not found")
            if old.status not in ("failed", "interrupted", "cancelled"):
                raise HTTPException(409, "Only failed, interrupted or cancelled jobs can be retried")
            kind, payload = old.kind, old.payload
        return enqueue(kind, payload)

    @app.post("/api/simulations", status_code=202)
    def start_simulation(config: SimulationRequest):
        revision = record(str(config.revision_id), "revision")
        if revision["config"]["operating_mode"] != "DEMO":
            raise HTTPException(422, "Only DEMO simulated mission records are implemented in P0/P1")
        mission_config = MissionConfig.model_validate(revision["config"])
        if config.expansion and (
            mission_config.schema_version != 2 or mission_config.weather.provider != "NOAA_GFS"
        ):
            raise HTTPException(422, "Automatic weather expansion requires solver schema 2 and NOAA GFS")
        if mission_config.weather.dataset_id:
            dataset = record(mission_config.weather.dataset_id, "dataset")
            start = mission_config.launch.start_utc
            from datetime import datetime, timedelta

            duration = mission_config.duration_s
            if datetime.fromisoformat(dataset["run_utc"]) > start:
                raise HTTPException(422, "Forecast initialized after launch; look-ahead rejected")
            if start < datetime.fromisoformat(dataset["valid_start_utc"]) or start + timedelta(
                seconds=duration
            ) > datetime.fromisoformat(dataset["valid_end_utc"]):
                raise HTTPException(
                    422, "Entire prescribed profile must fit the selected forecast valid-time horizon"
                )
            try:
                field = slices.get(data / "cache" / mission_config.weather.dataset_id, start)
                if field.provenance["sha256"] != dataset["sha256"]:
                    raise ValueError("Registered forecast identity differs from cached manifest")
                field.get_state(
                    mission_config.launch.latitude_deg,
                    mission_config.launch.longitude_deg,
                    mission_config.flight.initial_geometric_m,
                    start,
                )
            except (WeatherDomainError, ValueError, FileNotFoundError) as exc:
                raise HTTPException(422, f"Initial weather state is invalid: {exc}") from exc
        return enqueue(
            "simulation",
            {
                "revision_id": str(config.revision_id),
                "expansion": config.expansion.model_dump() if config.expansion else None,
            },
        )

    @app.get("/api/simulations")
    def simulations(limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        strings = [
            "name",
            "created_utc",
            "weather_provider",
            "revision_id",
            "model",
            "quality",
            "operating_mode",
            "solver_version",
        ]
        numbers = ["distance_m", "duration_s", "horizontal_air_distance_m"]
        with factory() as session:
            query = (
                select(
                    Record.id,
                    *[Record.payload[k].as_string().label(k) for k in strings],
                    *[Record.payload[k].as_float().label(k) for k in numbers],
                )
                .where(Record.kind == "simulation")
                .order_by(Record.created_utc.desc())
                .offset(offset)
                .limit(limit)
            )
            return [dict(r) for r in session.execute(query).mappings()]

    @app.post("/api/simulations/compare")
    def compare_simulations(config: ComparisonRequest):
        reference = record(str(config.reference_id), "simulation")
        candidate = record(str(config.candidate_id), "simulation")
        try:
            assert_runtime_unchanged(API_RUNTIME_CODE)
            result = compare_runs(reference, candidate, config)
            assert_runtime_unchanged(API_RUNTIME_CODE)
            result["code"] = {
                **API_RUNTIME_CODE,
                "identity_scope": "API startup scientific snapshot; checked before and after comparison",
            }
            result["comparison_sha256"] = digest(
                {k: v for k, v in result.items() if k != "comparison_sha256"}
            )
            return result
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/simulations/{simulation_id}")
    def get_simulation(simulation_id: UUID):
        return record(str(simulation_id), "simulation")

    @app.get("/api/simulations/{simulation_id}/trajectory")
    def trajectory(simulation_id: UUID):
        value = record(str(simulation_id), "simulation")
        return {
            "type": "Feature",
            "properties": {"simulation_id": str(simulation_id), "quality": "modeled_uncalibrated"},
            "geometry": geometry(value["samples"]),
        }

    @app.get("/api/simulations/{simulation_id}/export")
    def export_simulation(simulation_id: UUID, format: str = "json"):
        value = record(str(simulation_id), "simulation")
        if format == "csv":
            stream = io.StringIO()
            writer = csv.DictWriter(stream, fieldnames=list(value["samples"][0]))
            writer.writeheader()
            writer.writerows(value["samples"])
            body, media, ext = stream.getvalue(), "text/csv", "csv"
        elif format == "geojson":
            body, media, ext = (
                json.dumps(
                    {
                        "type": "Feature",
                        "properties": {
                            "simulation_id": str(simulation_id),
                            "quality": "modeled_uncalibrated",
                            "altitude_reference": "2D export; geometric MSL heights are in original sample data",
                            "output_sha256": value["manifest"]["output_sha256"],
                        },
                        "geometry": geometry(value["samples"]),
                    }
                ),
                "application/geo+json",
                "geojson",
            )
        elif format == "json":
            body, media, ext = json.dumps(value, indent=2, allow_nan=False), "application/json", "json"
        else:
            raise HTTPException(422, "Export format must be json, csv or geojson")
        return Response(
            body,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="stratos-{simulation_id}.{ext}"'},
        )

    dist = ROOT / "apps/web/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


app = create_app()
