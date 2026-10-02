"""Versioned public request contract; local place resolution happens upstream."""

from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from swiss_api.rules import current_rules


class BirthInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_date: date
    local_time: time | None = None
    birth_time_known: bool
    time_zone: str = Field(min_length=1, max_length=100)
    utc_datetime: datetime | None = None
    latitude_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_time(self) -> "BirthInput":
        try:
            zone = ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("time_zone must be a valid IANA time zone") from exc

        if self.birth_time_known:
            if self.local_time is None or self.utc_datetime is None:
                raise ValueError("known birth time requires local_time and utc_datetime")
            if self.utc_datetime.tzinfo is None:
                raise ValueError("utc_datetime must include an offset")
            if self.utc_datetime.utcoffset() != timedelta(0):
                raise ValueError("utc_datetime must use UTC (Z or +00:00)")
            local = self.utc_datetime.astimezone(zone)
            if local.date() != self.local_date or local.time().replace(tzinfo=None) != self.local_time:
                raise ValueError("utc_datetime does not match the local birth date and time")
        elif self.local_time is not None or self.utc_datetime is not None:
            raise ValueError("unknown birth time must not include local_time or utc_datetime")
        return self


class NatalOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zodiac: str = Field(default_factory=lambda: current_rules()["zodiac_system"])
    house_system: str = Field(default_factory=lambda: current_rules()["house_system"])
    orb_profile: str = Field(default_factory=lambda: current_rules()["orb_profile"])

    @model_validator(mode="after")
    def validate_supported_options(self) -> "NatalOptions":
        rules = current_rules()
        if self.zodiac != rules["zodiac_system"]:
            raise ValueError("requested zodiac system is not supported")
        if self.house_system != rules["house_system"]:
            raise ValueError("requested house system is not supported")
        if self.orb_profile != rules["orb_profile"]:
            raise ValueError("requested orb profile is not supported")
        return self


class NatalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    birth: BirthInput
    options: NatalOptions = Field(default_factory=NatalOptions)


class CalculationMetadata(BaseModel):
    engine: Literal["swiss_ephemeris"]
    engine_version: str
    wrapper_version: str
    ephemeris_dataset_sha256: str
    rules_version: str
    rules_sha256: str
    zodiac: str
    orb_profile: str
    house_system_requested: str
    house_system_used: str | None
    fallback_reason: str | None
    reference_utc_datetime: datetime
    reference_time_status: Literal["birth_time", "local_noon_not_birth_time"]


class BodyResult(BaseModel):
    id: str
    longitude_deg: float
    latitude_deg: float
    speed_longitude_deg_per_day: float
    retrograde: bool
    position_status: Literal["exact", "date_reference_only"]
    sign: str
    house: int | None


class AnglesResult(BaseModel):
    ascendant_deg: float
    descendant_deg: float
    mc_deg: float
    ic_deg: float


class HousesResult(BaseModel):
    status: Literal["computed", "unavailable"]
    cusps_deg: list[float] | None


class AspectResult(BaseModel):
    body1: str
    body2: str
    aspect_type: str
    exact_angle_deg: int
    actual_angle_deg: float
    orb_deg: float
    applying_or_separating: Literal["applying", "separating"] | None
    context: Literal["natal", "transit", "progression", "synastry", "composite", "solar_return"]


class AnalysisResult(BaseModel):
    chart_ruler: str | None
    house_rulers: list[dict[str, str | int]]
    element_balance: dict[str, int]
    modality_balance: dict[str, int]


class NatalResponse(BaseModel):
    schema_version: Literal["1.0"]
    chart_type: Literal["natal"]
    calculation: CalculationMetadata
    bodies: list[BodyResult]
    angles: AnglesResult | None
    houses: HousesResult
    aspects: list[AspectResult]
    analysis: AnalysisResult
    warnings: list[str]


class SkyLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)


class SkyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    utc_datetime: datetime
    location: SkyLocation | None = None

    @model_validator(mode="after")
    def validate_instant(self) -> "SkyRequest":
        if self.utc_datetime.tzinfo is None or self.utc_datetime.utcoffset() != timedelta(0):
            raise ValueError("utc_datetime must use UTC")
        if not 1800 <= self.utc_datetime.year <= 2399:
            raise ValueError("supported years are 1800 through 2399")
        return self


class SynastryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    first: NatalRequest | NatalResponse
    second: NatalRequest | NatalResponse


class TransitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    natal: NatalRequest | NatalResponse
    target: SkyRequest


class SkyCalculationMetadata(CalculationMetadata):
    reference_time_status: Literal["target_time"]


class SkyResponse(NatalResponse):
    chart_type: Literal["sky"]
    calculation: SkyCalculationMetadata


class OverlayResponse(BaseModel):
    schema_version: Literal["1.0"]
    chart_type: Literal["synastry", "transit"]
    first: NatalResponse
    second: NatalResponse | SkyResponse
    aspects: list[AspectResult]
    warnings: list[str]
