"""Single process durable worker; one OS lock excludes accidental duplicate workers."""

import logging
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, update

from packages.domain.models import Cancelled, DownloadRequest, ExpansionPolicy, MissionConfig, digest, utcnow
from packages.flight.integrator import simulate
from packages.meteo.adaptive import AdaptiveField
from packages.meteo.field import SyntheticField, WeatherField
from packages.meteo.gfs import atomic_json, fetch_subset, open_cached
from services.api.provenance import assert_runtime_unchanged, code_identity
from services.api.storage import DATA, Job, Record, sessions

log = logging.getLogger("stratos.worker")
RUNTIME_CODE = code_identity()


def run_one(session_factory, data: Path, stop=lambda: False) -> bool:
    with session_factory() as session:
        job = session.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_utc).limit(1))
        if not job:
            return False
        job_id, kind, payload = job.id, job.kind, job.payload
        claimed = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", message="Starting", updated_utc=utcnow())
            .returning(Job.id)
        ).scalar_one_or_none()
        if claimed is None:
            session.rollback()
            return True
        # The SQL predicate keeps claims atomic against simultaneous cancellation.
        session.commit()

    last_update = [0.0]
    last_fraction = [0.0]
    # A 73-file crop already requires >=12 minutes of NOAA pacing, before
    # network/decode time. Preserve a bounded but usable transfer allowance.
    deadline = time.monotonic() + (1800 if kind == "weather" else 900 if payload.get("expansion") else 120)

    def progress(fraction, message="Integrating WGS84 trajectory"):
        last_fraction[0] = max(last_fraction[0], float(fraction))
        if time.monotonic() - last_update[0] < 0.3 and fraction < 1:
            return
        with session_factory() as session:
            session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(progress=float(fraction), message=message, updated_utc=utcnow())
            )
            session.commit()
        last_update[0] = time.monotonic()

    last_cancel = [0.0, False]

    def cancelled():
        if time.monotonic() > deadline:
            raise TimeoutError(
                "Job exceeded its wall-clock budget (download: 30 min; expanding study: 15 min; cached study: 2 min)"
            )
        if stop():
            raise Cancelled("Worker stopped; job can be resubmitted with retained weather cache")
        if time.monotonic() - last_cancel[0] > 0.2:
            with session_factory() as session:
                current = session.get(Job, job_id)
                last_cancel[:] = [time.monotonic(), bool(current and current.cancel_requested)]
        return last_cancel[1]

    try:
        assert_runtime_unchanged(RUNTIME_CODE)
        if cancelled():
            raise Cancelled("Cancelled before execution")
        if kind == "weather":
            result = fetch_subset(
                DownloadRequest.model_validate(payload), data / "cache", progress, cancelled
            )
            result_id, record_kind = result["id"], "dataset"
        elif kind == "telemetry_recovery":
            from packages.telemetry.models import RecoveryRequest
            from packages.telemetry.recovery import simulate_recovery

            configuration = RecoveryRequest.model_validate(payload)
            output = simulate_recovery(configuration, progress, cancelled)
            assert_runtime_unchanged(RUNTIME_CODE)
            result_id, record_kind = str(uuid4()), "telemetry_study"
            result = {
                "id": result_id,
                "kind": record_kind,
                "schema_version": 1,
                "created_utc": utcnow().isoformat(),
                "configuration": configuration.model_dump(mode="json"),
                "code": RUNTIME_CODE,
                "output_sha256": digest(output),
                "output": output,
            }
            result["sha256"] = digest(result)
        else:
            with session_factory() as session:
                revision = session.get(Record, payload["revision_id"])
                if revision is None or revision.kind != "revision":
                    raise ValueError("Mission revision does not exist")
                config = MissionConfig.model_validate(revision.payload["config"])
                registered = (
                    session.get(Record, str(config.weather.dataset_id)) if config.weather.dataset_id else None
                )
                expected_weather_hash = registered.payload.get("sha256") if registered else None
            if config.operating_mode != "DEMO":
                raise ValueError(
                    "P0/P1 supports simulated mission records in DEMO mode only; replay/test/live are deferred"
                )
            weather: WeatherField
            if config.weather.provider == "SYNTHETIC":
                weather = SyntheticField()
            else:
                directory = data / "cache" / str(config.weather.dataset_id)
                if config.schema_version == 1:
                    weather = open_cached(directory, legacy_surface_boundary=True)
                else:
                    initial = open_cached(directory, at_time=config.launch.start_utc)
                    policy = (
                        ExpansionPolicy.model_validate(payload["expansion"])
                        if payload.get("expansion")
                        else None
                    )
                    weather = AdaptiveField(
                        initial,
                        data / "cache",
                        policy,
                        lambda f, m: progress(last_fraction[0], "Adjacent crop: " + m),
                        cancelled,
                    )
                if datetime.fromisoformat(weather.provenance["run_utc"]) > config.launch.start_utc:
                    raise ValueError("Forecast initialized after simulated launch: look-ahead rejected")
                if expected_weather_hash and weather.provenance.get("sha256") != expected_weather_hash:
                    raise ValueError(
                        "Weather cache identity changed since dataset registration; refusing different inputs"
                    )
            output = simulate(config, weather, progress, cancelled)
            assert_runtime_unchanged(RUNTIME_CODE)
            result_id, record_kind = str(uuid4()), "simulation"
            manifest = {
                "schema_version": 1,
                "simulation_id": result_id,
                "created_utc": utcnow().isoformat(),
                "mission_id": str(config.id),
                "revision_id": payload["revision_id"],
                "config_sha256": config.revision_hash,
                "config": config.model_dump(mode="json"),
                "execution": {"expansion": payload.get("expansion")},
                "weather": weather.provenance,
                "code": {
                    **RUNTIME_CODE,
                    "identity_scope": "worker startup snapshot; scientific source and package versions checked before/after calculation",
                },
                "seed": None,
                "rng_used": False,
                "units": {"altitude": "geometric_msl_m", "pressure": "Pa", "temperature": "K", "wind": "m/s"},
                "altitude_conversion": "H=6356766*z/(6356766+z), standard geopotential reference radius",
                "output_sha256": digest(output),
            }
            manifest["sha256"] = digest(manifest)
            result = {
                "id": result_id,
                "name": config.name,
                "created_utc": manifest["created_utc"],
                "revision_id": payload["revision_id"],
                "operating_mode": config.operating_mode,
                "weather_provider": config.weather.provider,
                "manifest": manifest,
                **output,
            }
            atomic_json(data / "simulations" / f"{result_id}.json", result)
        if cancelled():
            raise Cancelled("Cancelled before committing result")
        with session_factory() as session:
            final_job = session.get(Job, job_id)
            if final_job and final_job.cancel_requested:
                raise Cancelled("Cancellation requested before result commit")
            if not session.get(Record, result_id):
                session.add(Record(id=result_id, kind=record_kind, payload=result))
            session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status="completed",
                    progress=1,
                    message="Completed and saved",
                    result_id=result_id,
                    updated_utc=utcnow(),
                )
            )
            session.commit()
    except Exception as exc:
        status = "cancelled" if isinstance(exc, Cancelled) else "failed"
        log.exception("Job %s %s", job_id, status)
        with session_factory() as session:
            session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(status=status, message=f"{type(exc).__name__}: {exc}", updated_utc=utcnow())
            )
            session.commit()
    return True


def recover_interrupted(session_factory):
    with session_factory() as session:
        session.execute(
            update(Job)
            .where(Job.status == "running")
            .values(
                status="interrupted",
                message="Worker restarted during job. Resubmit explicitly; verified weather cache is reusable.",
                updated_utc=utcnow(),
            )
        )
        session.commit()


def main():
    # OS file locks release after crashes; no stale pid-file based ownership.
    lock_path = DATA / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("a+")
    try:
        if sys.platform == "win32":
            import msvcrt

            lock.write("0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise SystemExit("Another STRATOS worker holds the data-directory lock") from exc
    logging.basicConfig(level=logging.INFO)
    session_factory = sessions()
    recover_interrupted(session_factory)
    stop = threading.Event()
    import os

    runtime = {"pid": os.getpid(), "started_utc": utcnow().isoformat()}

    def heartbeat():
        while not stop.is_set():
            try:
                with session_factory() as session:
                    row = session.get(Record, "runtime_worker")
                    changed = (
                        code_identity()["scientific_source_sha256"]
                        != RUNTIME_CODE["scientific_source_sha256"]
                    )
                    payload = {**runtime, "heartbeat_utc": utcnow().isoformat(), "code_changed": changed}
                    if row:
                        row.payload = payload
                    else:
                        session.add(Record(id="runtime_worker", kind="runtime", payload=payload))
                    session.commit()
            except Exception:
                log.exception("Worker heartbeat could not be persisted")
            stop.wait(2)

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("Durable worker ready")
    while not stop.is_set():
        if not run_one(session_factory, DATA, stop.is_set):
            stop.wait(0.5)
    heartbeat_thread.join(timeout=3)
    lock.close()


if __name__ == "__main__":
    main()
