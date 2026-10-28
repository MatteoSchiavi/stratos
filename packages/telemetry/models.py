from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Observation(StrictModel):
    time_s: int = Field(ge=0, le=16777215)
    sequence: int = Field(ge=0, le=65535)
    latitude_deg: float | None = Field(default=None, ge=-90, le=90)
    longitude_deg: float | None = Field(default=None, ge=-180, le=180)
    altitude_m: float | None = Field(default=None, ge=-32767, le=32767)
    temperature_k: float | None = Field(default=None, ge=0, le=500)
    voltage_v: float | None = Field(default=None, ge=0, le=65.534)
    pressure_pa: float | None = Field(default=None, ge=0, le=16777214)
    clock_valid: bool = True
    fix_valid: bool = True
    origin: Literal["measured", "simulated", "assumed"] = "assumed"

    @model_validator(mode="after")
    def position_pair(self):
        if (self.latitude_deg is None) != (self.longitude_deg is None):
            raise ValueError("Latitude and longitude must both be present or absent")
        return self


class CodecRequest(StrictModel):
    family: Literal["NAV", "NAV+ENV", "HISTORY", "EMERGENCY"] = "NAV+ENV"
    observations: list[Observation] = Field(min_length=1, max_length=32)


class DecodeRequest(StrictModel):
    hex: str = Field(max_length=8192, pattern=r"^[0-9a-fA-F ]+$")


class RadioRequest(StrictModel):
    region: Literal["EU868", "US915"] = "EU868"
    data_rate: int = Field(default=5, ge=0, le=15)
    application_bytes: int = Field(default=24, ge=1, le=4096)
    fopts_bytes: int = Field(default=0, ge=0, le=15)
    dwell_limit_ms: float | None = Field(default=None, gt=0, le=400)


class BatchRequest(StrictModel):
    radio: RadioRequest = Field(default_factory=RadioRequest)
    observations: list[Observation] = Field(min_length=1, max_length=32)
    sample_interval_s: float = Field(default=60, ge=1, le=86400)
    horizon_s: int = Field(default=3600, ge=60, le=259200)
    available_airtime_s: float = Field(default=30, gt=0, le=86400)
    loss_probability: float = Field(default=0.2, ge=0, le=1)
    max_fresh_interval_s: float = Field(default=600, ge=1, le=86400)


class ArchiveRequest(StrictModel):
    observations: list[Observation] = Field(default_factory=list, max_length=5000)
    simulation_id: UUID | None = None
    epoch_utc: datetime | None = None
    trajectory_tolerance_m: float = Field(default=100, gt=0, le=100000)

    @field_validator("epoch_utc")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Explicit UTC offset required for archive epoch")
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def source(self):
        if bool(self.observations) == bool(self.simulation_id):
            raise ValueError("Choose observations or one saved simulation, exclusively")
        return self


class Window(StrictModel):
    start_s: float = Field(ge=0, le=259200)
    end_s: float = Field(gt=0, le=259200)

    @model_validator(mode="after")
    def interval(self):
        if self.end_s <= self.start_s:
            raise ValueError("Window end must be after start")
        return self


class Contact(Window):
    receiver_id: str = Field(min_length=1, max_length=80)
    region: Literal["EU868", "US915"]
    data_rates: list[int] = Field(min_length=1, max_length=7)
    channels_hz: list[int] | None = Field(default=None, max_length=72)
    compatible: bool = False
    evidence: Literal["assumed", "predicted", "observed"] = "assumed"
    source: str = Field(min_length=1, max_length=200)
    loss_probability: float = Field(default=0.2, ge=0, le=1)

    @model_validator(mode="after")
    def regional_settings(self):
        allowed = range(7) if self.region == "EU868" else range(5)
        if any(dr not in allowed for dr in self.data_rates):
            raise ValueError("Receiver data rates must be supported uplinks for its declared region")
        if self.channels_hz is not None:
            supported = (
                {868100000, 868300000, 868500000}
                if self.region == "EU868"
                else {902300000 + i * 200000 for i in range(64)} | {903000000 + i * 1600000 for i in range(8)}
            )
            if not self.channels_hz or any(f not in supported for f in self.channels_hz):
                raise ValueError("Receiver channel mask is outside the supported regional frequency plan")
        return self


class RegionProfile(Window):
    name: str = Field(min_length=1, max_length=80)
    region: Literal["EU868", "US915"]
    south: float = Field(ge=-90, le=90)
    north: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    east: float = Field(ge=-180, le=180)
    permission_configured: bool = False
    permission_reference: str = Field(default="", max_length=200)
    duty_fraction: float = Field(default=0.01, gt=0, le=1)
    dwell_limit_ms: float | None = Field(default=None, gt=0, le=400)

    @model_validator(mode="after")
    def bounds(self):
        if self.north <= self.south or self.west == self.east:
            raise ValueError("Region rectangle has zero/inverted area")
        if self.region == "EU868" and self.duty_fraction > 0.01:
            raise ValueError(
                "Supported EU868 profile is conservative1% shared sub-band; higher limits unsupported"
            )
        if self.permission_configured and not self.permission_reference.strip():
            raise ValueError("Configured permission requires a reference; this is not software authorization")
        return self


class Power(StrictModel):
    battery_initial_j: float = Field(default=1000, ge=0, le=10000000)
    battery_capacity_j: float = Field(default=1200, gt=0, le=10000000)
    reserve_j: float = Field(default=50, ge=0, le=10000000)
    harvest_w: float = Field(default=0, ge=0, le=100)
    idle_w: float = Field(default=0.002, ge=0, le=100)
    tx_w: float = Field(default=0.15, gt=0, le=100)
    rx_allowance_j: float = Field(default=0.01, ge=0, le=100)
    capacitor_f: float = Field(default=1, gt=0, le=10000)
    initial_voltage_v: float = Field(default=4.5, gt=0, le=100)
    max_voltage_v: float = Field(default=5, gt=0, le=65.534)
    wake_voltage_v: float = Field(default=4.4, gt=0, le=100)
    sleep_voltage_v: float = Field(default=3.5, gt=0, le=100)
    charge_w: float = Field(default=0.05, gt=0, le=100)
    efficiency: float = Field(default=0.85, gt=0, le=1)

    @model_validator(mode="after")
    def thresholds(self):
        if not self.sleep_voltage_v < self.wake_voltage_v <= self.max_voltage_v:
            raise ValueError("Capacitor requires sleep < wake <= maximum voltage")
        if self.initial_voltage_v > self.max_voltage_v:
            raise ValueError("Initial voltage exceeds capacitor maximum")
        if self.battery_initial_j > self.battery_capacity_j or self.reserve_j > self.battery_capacity_j:
            raise ValueError("Battery initial/reserve exceeds capacity")
        return self


class PositionSource(StrictModel):
    simulation_id: UUID
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecoveryRequest(StrictModel):
    position_source: PositionSource | None = None
    epoch_utc: datetime = datetime(2026, 10, 27, 18, tzinfo=UTC)

    @field_validator("epoch_utc")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Explicit UTC offset required for mission epoch")
        return value.astimezone(UTC)

    schema_version: Literal[1] = 1
    duration_s: int = Field(default=3600, ge=60, le=259200)
    step_s: int = Field(default=10, ge=1, le=60)
    sample_interval_s: int = Field(default=60, ge=10, le=3600)
    fresh_interval_s: int = Field(default=300, ge=10, le=86400)
    max_fix_age_s: int = Field(default=300, ge=1, le=3600)
    history_batch: int = Field(default=4, ge=1, le=32)
    history_repeats: int = Field(default=2, ge=1, le=10)
    seed: int = Field(default=42, ge=0, le=4294967295)
    fopts_bytes: int = Field(default=0, ge=0, le=15)
    fair_use_s_per_24h: float | None = Field(default=30, gt=0, le=86400)
    fresh_airtime_fraction: float = Field(default=0.8, gt=0, le=1)
    positions: list[Observation] = Field(min_length=1, max_length=5000)
    contacts: list[Contact] = Field(default_factory=list, max_length=64)
    outages: list[Window] = Field(default_factory=list, max_length=64)
    profiles: list[RegionProfile] = Field(default_factory=list, max_length=32)
    power: Power = Field(default_factory=Power)

    @model_validator(mode="after")
    def workload(self):
        if self.duration_s / self.step_s > 30000 or self.duration_s / self.sample_interval_s > 5000:
            raise ValueError("Study exceeds30000 scheduling steps or5000 observations")
        if any(a.time_s >= b.time_s for a, b in zip(self.positions, self.positions[1:], strict=False)):
            raise ValueError("Position times must be strictly increasing")
        return self
