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
from swiss_api.rules import current_rules, rules_sha256


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


def _sign_for_longitude(longitude_deg: float, rules: dict) -> dict:
    return rules["signs"][int(longitude_deg % 360 // 30)]


def _house_for_longitude(longitude_deg: float, cusps_deg: list[float]) -> int:
    """Return the one-based house containing longitude, including its cusp."""
    for index, cusp in enumerate(cusps_deg):
        if abs((longitude_deg - cusp + 180) % 360 - 180) < 1e-9:
            return index + 1
    for index, start in enumerate(cusps_deg):
        end = cusps_deg[(index + 1) % len(cusps_deg)]
        span = (end - start) % 360
        if (longitude_deg - start) % 360 < span:
            return index + 1
    raise RuntimeError("house cusps do not cover the zodiac")


def configured_aspects(bodies: list[dict], context: str, rules: dict) -> list[dict]:
    """Apply the configured HOSHIYUME orb profile, including its boundaries."""
    found = []
    for a, b in combinations(bodies, 2):
        separation = abs((a["longitude_deg"] - b["longitude_deg"] + 180) % 360 - 180)
        for aspect in rules["aspects"]:
            orb = abs(separation - aspect["angle_deg"])
            if orb <= aspect["orb_deg"]:
                found.append({
                    "body1": a["id"],
                    "body2": b["id"],
                    "aspect_type": aspect["id"],
                    "exact_angle_deg": aspect["angle_deg"],
                    "actual_angle_deg": separation,
                    "orb_deg": orb,
                    # Progression and transit add a time-direction calculation later.
                    "applying_or_separating": None,
                    "context": context,
                })
                break
    return found


def major_aspects(bodies: list[dict]) -> list[dict]:
    """Backward-compatible test helper for the standard natal rules."""
    return configured_aspects(bodies, "natal", current_rules())


def _basic_analysis(
    bodies: list[dict],
    angles: dict[str, float] | None,
    houses: dict,
    rules: dict,
) -> dict:
    element_balance = {key: 0 for key in ("fire", "earth", "air", "water")}
    modality_balance = {key: 0 for key in ("cardinal", "fixed", "mutable")}
    included_ids = {body["id"] for body in rules["bodies"] if body.get("include_in_balance")}
    for body in bodies:
        if body["id"] in included_ids:
            sign = _sign_for_longitude(body["longitude_deg"], rules)
            element_balance[sign["element"]] += 1
            modality_balance[sign["modality"]] += 1

    house_rulers: list[dict[str, str | int]] = []
    chart_ruler: str | None = None
    if angles is not None and houses["cusps_deg"] is not None:
        asc_sign = _sign_for_longitude(angles["ascendant_deg"], rules)
        chart_ruler = asc_sign["ruler"]
        for house_number, cusp in enumerate(houses["cusps_deg"], start=1):
            sign = _sign_for_longitude(cusp, rules)
            house_rulers.append({"house": house_number, "sign": sign["id"], "ruler": sign["ruler"]})
    return {
        "chart_ruler": chart_ruler,
        "house_rulers": house_rulers,
        "element_balance": element_balance,
        "modality_balance": modality_balance,
    }


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
        rules = current_rules()
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
        calculated_by_id: dict[str, dict] = {}
        for body_rule in rules["bodies"]:
            body_id = body_rule["id"]
            if "derived_from" in body_rule:
                source = calculated_by_id.get(body_rule["derived_from"])
                if source is None:
                    raise RuntimeError("derived body is ordered before its source")
                body = {
                    **source,
                    "id": body_id,
                    "longitude_deg": (source["longitude_deg"] + body_rule.get("longitude_offset_deg", 0)) % 360,
                    "sign": _sign_for_longitude(
                        source["longitude_deg"] + body_rule.get("longitude_offset_deg", 0), rules,
                    )["id"],
                }
                bodies.append(body)
                calculated_by_id[body_id] = body
                continue
            swiss_id = getattr(swe, body_rule["swiss_constant"])
            try:
                values, flags = swe.calc_ut(julian_day, swiss_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
            except swe.Error as exc:
                raise EphemerisUnavailable("Swiss planetary calculation failed") from exc
            if not flags & swe.FLG_SWIEPH:
                raise EphemerisUnavailable("Swiss calculation fell back to a different ephemeris")
            body = {
                "id": body_id,
                "longitude_deg": values[0] % 360,
                "latitude_deg": values[1],
                "speed_longitude_deg_per_day": values[3],
                "retrograde": values[3] < 0,
                "position_status": "exact" if birth.birth_time_known else "date_reference_only",
                "sign": _sign_for_longitude(values[0], rules)["id"],
                "house": None,
            }
            bodies.append(body)
            calculated_by_id[body_id] = body

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
                    cusps, points = swe.houses_ex(
                        julian_day,
                        birth.latitude_deg,
                        birth.longitude_deg,
                        rules["house_system_swiss_code"].encode("ascii"),
                    )
                    used_house_system = request.options.house_system
                except swe.Error:
                    # Swiss may return Porphyry cusps on Placidus failure. Discard them.
                    fallback = rules["house_system_fallback"]
                    fallback_reason = fallback["reason"]
                    try:
                        cusps, points = swe.houses_ex(
                            julian_day,
                            birth.latitude_deg,
                            birth.longitude_deg,
                            fallback["swiss_code"].encode("ascii"),
                        )
                        used_house_system = fallback["id"]
                        warnings.append("house_system_changed_to_whole_sign")
                    except swe.Error:
                        warnings.append("houses_unavailable")
                if used_house_system is not None:
                    angles = {
                        "ascendant_deg": points[0] % 360,
                        "descendant_deg": (points[0] + 180) % 360,
                        "mc_deg": points[1] % 360,
                        "ic_deg": (points[1] + 180) % 360,
                    }
                    houses = {"status": "computed", "cusps_deg": [value % 360 for value in cusps]}
                    for body in bodies:
                        body["house"] = _house_for_longitude(body["longitude_deg"], houses["cusps_deg"])
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
                "rules_version": rules["rules_version"],
                "rules_sha256": rules_sha256(),
                "zodiac": request.options.zodiac,
                "orb_profile": request.options.orb_profile,
                "house_system_requested": request.options.house_system,
                "house_system_used": used_house_system,
                "fallback_reason": fallback_reason,
                "reference_utc_datetime": reference.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "reference_time_status": "birth_time" if birth.birth_time_known else "local_noon_not_birth_time",
            },
            "bodies": bodies,
            "angles": angles,
            "houses": houses,
            "aspects": configured_aspects(bodies, "natal", rules) if birth.birth_time_known else [],
            "analysis": _basic_analysis(bodies, angles, houses, rules),
            "warnings": warnings,
        }
