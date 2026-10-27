"""Versioned SI-only mission exchange. No hardware capability is implied."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class Launch(StrictModel):
    latitude_deg: float = Field(default=45.05, ge=-89.5, le=89.5)
    longitude_deg: float = Field(default=9.70, ge=-180, le=180)
    ground_geometric_m: float = Field(default=80, ge=-400, le=6000)
    start_utc: datetime = datetime(2026, 10, 27, 12, tzinfo=UTC)

    @field_validator("start_utc")
    @classmethod
    def require_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("Explicit UTC offset required; naive local time is not accepted")
        return v.astimezone(UTC)


class FlightProfile(StrictModel):
    model: Literal["L0_prescribed"] = "L0_prescribed"
    initial_geometric_m: float = Field(default=80, ge=-400, le=20000)
    target_geometric_m: float = Field(default=12500, ge=100, le=20000)
    ascent_ms: float = Field(default=1.5, gt=0, le=15)
    float_duration_hours: float = Field(default=6, gt=0, le=72)
    descent_ms: float | None = Field(default=None, gt=0, le=30)
    payload_mass_g: float = Field(default=23, gt=0, le=3000)
    integration_step_s: int = Field(default=30, ge=5, le=120)
    sample_interval_s: int = Field(default=120, ge=30, le=300)


class WeatherConfig(StrictModel):
    provider: Literal["SYNTHETIC", "NOAA_GFS"] = "SYNTHETIC"
    dataset_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")


class RadioConfig(StrictModel):
    enabled: Literal[False] = False


class MissionConfig(StrictModel):
    schema_version: Literal[1, 2] = 2
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(default="STRATOS / Design study 01", min_length=1, max_length=100)
    operating_mode: Literal["DEMO", "HISTORICAL_REPLAY", "HARDWARE_TEST", "LIVE"] = "DEMO"
    origin: Literal["assumed", "demo"] = "assumed"
    calibration_status: Literal["uncalibrated"] = "uncalibrated"
    launch: Launch = Field(default_factory=Launch)
    flight: FlightProfile = Field(default_factory=FlightProfile)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    radio: RadioConfig = Field(default_factory=RadioConfig)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.flight.initial_geometric_m < self.launch.ground_geometric_m:
            raise ValueError("Initial altitude must be at or above configured ground (geometric MSL m)")
        if self.flight.target_geometric_m < self.flight.initial_geometric_m:
            raise ValueError("Target altitude must be at or above initial altitude")
        if self.weather.provider == "NOAA_GFS" and not self.weather.dataset_id:
            raise ValueError("NOAA_GFS requires an explicitly downloaded dataset_id")
        if self.weather.provider == "SYNTHETIC" and self.weather.dataset_id is not None:
            raise ValueError("Synthetic provider cannot reference a NOAA dataset")
        if self.duration_s > 72 * 3600:
            raise ValueError("Total prescribed ascent + float + descent exceeds the 72-hour compute limit")
        return self

    @property
    def duration_s(self) -> float:
        f = self.flight
        return (
            (f.target_geometric_m - f.initial_geometric_m) / f.ascent_ms
            + f.float_duration_hours * 3600
            + ((f.target_geometric_m - self.launch.ground_geometric_m) / f.descent_ms if f.descent_ms else 0)
        )

    @property
    def revision_hash(self) -> str:
        return digest(self.model_dump(mode="json"))


class DownloadRequest(StrictModel):
    run_utc: datetime
    first_lead_hour: int = Field(default=0, ge=0, le=119)
    last_lead_hour: int = Field(default=48, ge=1, le=120)
    west_deg: float = Field(default=5, ge=-180, le=180)
    east_deg: float = Field(default=20, ge=-180, le=180)
    south_deg: float = Field(default=40, ge=-89.5, le=89.5)
    north_deg: float = Field(default=52, ge=-89.5, le=89.5)

    @field_validator("run_utc")
    @classmethod
    def cycle(cls, v: datetime) -> datetime:
        v = Launch.require_utc(v)
        if v.hour not in (0, 6, 12, 18) or v.minute or v.second or v.microsecond:
            raise ValueError("GFS cycle must be exactly 00/06/12/18 UTC")
        if v > utcnow():
            raise ValueError("Cannot download a future initialization")
        return v

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.first_lead_hour >= self.last_lead_hour:
            raise ValueError("At least two consecutive forecast leads are required")
        if self.last_lead_hour - self.first_lead_hour > 72:
            raise ValueError("A cropped forecast window may span at most 72 hours (73 hourly files)")
        if not 0.5 <= self.east_deg - self.west_deg <= 60:
            raise ValueError("P1 NOAA ROI width must be 0.5–60 degrees without crossing the dateline")
        if not 0.5 <= self.north_deg - self.south_deg <= 40:
            raise ValueError("P1 NOAA ROI height must be 0.5–40 degrees")
        return self


class SimulationRequest(StrictModel):
    revision_id: UUID
    expansion: "ExpansionPolicy | None" = None


class ExpansionPolicy(StrictModel):
    max_tiles: int = Field(default=8, ge=1, le=16)
    max_download_mib: int = Field(default=64, ge=1, le=128)


class ExploreRequest(StrictModel):
    dataset_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    time_utc: datetime
    latitude_deg: float = Field(ge=-89.5, le=89.5)
    longitude_deg: float = Field(ge=-180, le=180)
    geometric_msl_m: float = Field(default=12500, ge=-400, le=20000)
    grid_size: int = Field(default=9, ge=3, le=13)
    plane: Literal["geometric_altitude", "isobaric"] = "geometric_altitude"
    pressure_pa: float | None = Field(default=None, ge=5000, le=100000)
    contour_variable: Literal["wind_speed", "temperature"] = "wind_speed"
    contour_grid_size: Literal[17, 25, 33] = 25

    @model_validator(mode="after")
    def selected_plane(self) -> Self:
        if self.plane == "isobaric" and self.pressure_pa is None:
            raise ValueError("An isobaric view requires an explicit retained pressure level in Pa")
        if self.plane == "geometric_altitude" and self.pressure_pa is not None:
            raise ValueError("Pressure must be omitted for a geometric-altitude view")
        return self

    @field_validator("time_utc")
    @classmethod
    def zoned_time(cls, v: datetime) -> datetime:
        return Launch.require_utc(v)


class Cancelled(Exception):
    pass


class ComparisonRequest(StrictModel):
    reference_id: UUID
    candidate_id: UUID
    alignment: Literal["elapsed", "utc"] = "elapsed"
    sample_count: int = Field(default=241, ge=3, le=1001)

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if self.reference_id == self.candidate_id:
            raise ValueError("Select two distinct saved studies")
        return self
