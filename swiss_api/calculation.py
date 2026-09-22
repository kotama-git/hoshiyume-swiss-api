"""Swiss Ephemeris adapter. No names, user IDs, interpretation, or persistence."""

from datetime import datetime, time, timezone
from functools import wraps
from hashlib import sha256
from importlib.metadata import version
from itertools import combinations
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

import swisseph as swe

from swiss_api.models import NatalRequest


class EphemerisUnavailable(Exception):
    """Calculation cannot be guaranteed to use the configured Swiss data files."""


_SWISS_LOCK = RLock()


def _serialized_swiss_call(method):
    """The native library keeps process-global calculation and file-path state."""
    @wraps(method)
    def wrapped(*args, **kwargs):
        with _SWISS_LOCK:
            return method(*args, **kwargs)
    return wrapped


BODIES = (
    ("sun", swe.SUN),
    ("moon", swe.MOON),
    ("mercury", swe.MERCURY),
    ("venus", swe.VENUS),
    ("mars", swe.MARS),
    ("jupiter", swe.JUPITER),
    ("saturn", swe.SATURN),
    ("uranus", swe.URANUS),
    ("neptune", swe.NEPTUNE),
    ("pluto", swe.PLUTO),
)

ASPECTS = (
    ("conjunction", 0, 8),
    ("sextile", 60, 4),
    ("square", 90, 6),
    ("trine", 120, 6),
    ("opposition", 180, 8),
)


def major_aspects(bodies: list[dict]) -> list[dict]:
    """Natal major_v1: 10 planets, fixed orbs, including the boundary."""
    found = []
    for a, b in combinations(bodies, 2):
        separation = abs((a["longitude_deg"] - b["longitude_deg"] + 180) % 360 - 180)
        for kind, exact_angle, limit in ASPECTS:
            orb = abs(separation - exact_angle)
            if orb <= limit:
                found.append({
                    "a": a["id"], "b": b["id"], "type": kind,
                    "exact_angle_deg": exact_angle, "orb_deg": orb,
                })
                break
    return found


def _julian_day(instant: datetime) -> float:
    utc = instant.astimezone(timezone.utc)
    hour = utc.hour + utc.minute / 60 + utc.second / 3600 + utc.microsecond / 3_600_000_000
    return swe.julday(utc.year, utc.month, utc.day, hour, swe.GREG_CAL)


class SwissEngine:
    def __init__(self, ephe_path: Path | None):
        self.ephe_path = ephe_path
        self.data_files = (
            sorted((*ephe_path.glob("sepl_*.se1"), *ephe_path.glob("semo_*.se1")))
            if ephe_path and ephe_path.is_dir() else []
        )
        self.ready = (
            any(path.name.startswith("sepl_") for path in self.data_files)
            and any(path.name.startswith("semo_") for path in self.data_files)
        )
        self.dataset_hash = self._dataset_hash() if self.ready else None

    def _dataset_hash(self) -> str:
        digest = sha256()
        for path in self.data_files:
            digest.update(path.name.encode("utf-8"))
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    @_serialized_swiss_call
    def natal(self, request: NatalRequest) -> dict:
        if not self.ready or self.ephe_path is None:
            raise EphemerisUnavailable("Swiss ephemeris data files are not configured")
        swe.set_ephe_path(str(self.ephe_path))
        birth = request.birth
        if birth.birth_time_known:
            reference = birth.utc_datetime
            assert reference is not None
        else:
            # A reference instant for date-based positions, never an asserted birth time.
            reference = datetime.combine(birth.local_date, time(12), ZoneInfo(birth.time_zone))
            round_trip = reference.astimezone(timezone.utc).astimezone(ZoneInfo(birth.time_zone))
            if round_trip.date() != birth.local_date or round_trip.time().replace(tzinfo=None) != time(12):
                raise ValueError("local birth date is invalid in the selected time zone")

        julian_day = _julian_day(reference)
        bodies = []
        for body_id, swiss_id in BODIES:
            try:
                values, flags = swe.calc_ut(julian_day, swiss_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
            except swe.Error as exc:
                raise EphemerisUnavailable("Swiss planetary calculation failed") from exc
            if not flags & swe.FLG_SWIEPH:
                raise EphemerisUnavailable("Swiss calculation fell back to a different ephemeris")
            bodies.append({
                "id": body_id,
                "longitude_deg": values[0] % 360,
                "latitude_deg": values[1],
                "speed_longitude_deg_per_day": values[3],
                "retrograde": values[3] < 0,
                "position_status": "exact" if birth.birth_time_known else "date_reference_only",
            })

        angles: dict[str, float] | None = None
        houses: dict = {"status": "unavailable", "cusps_deg": None}
        used_house_system: str | None = None
        fallback_reason: str | None = None
        warnings: list[str] = []
        if birth.birth_time_known:
            if abs(birth.latitude_deg) >= 89.9999:
                warnings.append("geographic_pole_houses_unavailable")
            else:
                try:
                    cusps, points = swe.houses_ex(julian_day, birth.latitude_deg, birth.longitude_deg, b"P")
                    used_house_system = "placidus"
                except swe.Error:
                    # Swiss may return Porphyry cusps on Placidus failure. Discard them.
                    fallback_reason = "placidus_unavailable"
                    try:
                        cusps, points = swe.houses_ex(julian_day, birth.latitude_deg, birth.longitude_deg, b"W")
                        used_house_system = "whole_sign"
                        warnings.append("house_system_changed_to_whole_sign")
                    except swe.Error:
                        warnings.append("houses_unavailable")
                if used_house_system is not None:
                    angles = {"ascendant_deg": points[0] % 360, "mc_deg": points[1] % 360}
                    houses = {"status": "computed", "cusps_deg": [value % 360 for value in cusps]}
        else:
            warnings.append("birth_time_unknown_no_angles_houses_or_firm_aspects")

        return {
            "schema_version": "1.0",
            "chart_type": "natal",
            "calculation": {
                "engine": "swiss_ephemeris",
                "engine_version": swe.version,
                "wrapper_version": version("pyswisseph"),
                "ephemeris_dataset_sha256": self.dataset_hash,
                "rules_version": "natal_v1",
                "zodiac": "tropical",
                "aspect_profile": "major_v1",
                "house_system_requested": "placidus",
                "house_system_used": used_house_system,
                "fallback_reason": fallback_reason,
                "reference_utc_datetime": reference.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "reference_time_status": "birth_time" if birth.birth_time_known else "local_noon_not_birth_time",
            },
            "bodies": bodies,
            "angles": angles,
            "houses": houses,
            "aspects": major_aspects(bodies) if birth.birth_time_known else [],
            "warnings": warnings,
        }
