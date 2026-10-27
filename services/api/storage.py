import os
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, Boolean, DateTime, Float, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from packages.domain.models import utcnow

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("STRATOS_DATA_DIR", ROOT / "data")).resolve()


class Base(DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True, default="queued")
    payload: Mapped[dict] = mapped_column(JSON)
    progress: Mapped[float] = mapped_column(Float, default=0)
    message: Mapped[str] = mapped_column(String, default="Waiting for worker")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    result_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_engine(data: Path = DATA):
    data.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data / 'stratos.sqlite3'}", connect_args={"timeout": 20})

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


def migrate(engine):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def sessions(data: Path = DATA):
    return sessionmaker(make_engine(data), expire_on_commit=False)


if __name__ == "__main__":
    migrate(make_engine())
    print("SQLite schema migrated to head")
