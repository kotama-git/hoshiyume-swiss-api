"""Optional smoke test; never silently accepts the Moshier fallback."""

import os
from pathlib import Path

import pytest

from swiss_api.calculation import SwissEngine
from swiss_api.models import NatalRequest


@pytest.mark.skipif(not os.getenv("SWISS_EPHE_PATH"), reason="official ephemeris data not configured")
def test_real_swiss_data_produces_plausible_reference_positions():
    engine = SwissEngine(Path(os.environ["SWISS_EPHE_PATH"]))
    request = NatalRequest.model_validate({
        "schema_version": "1.0",
        "birth": {
            "local_date": "2000-01-01",
            "local_time": "21:00:00",
            "birth_time_known": True,
            "time_zone": "Asia/Tokyo",
            "utc_datetime": "2000-01-01T12:00:00Z",
            "latitude_deg": 35.68,
            "longitude_deg": 139.76,
        },
    })
    result = engine.natal(request)
    sun = next(body for body in result["bodies"] if body["id"] == "sun")
    moon = next(body for body in result["bodies"] if body["id"] == "moon")
    # Regression values from the official _18 data files (DE441, 2026 release).
    assert sun["longitude_deg"] == pytest.approx(280.368919, abs=0.02)
    assert moon["longitude_deg"] == pytest.approx(223.323751, abs=0.02)
    assert result["calculation"]["house_system_used"] == "placidus"
    assert result["angles"]["ascendant_deg"] == pytest.approx(155.339638, abs=0.02)
    assert result["houses"]["cusps_deg"][0] == pytest.approx(result["angles"]["ascendant_deg"])
    assert result["houses"]["cusps_deg"][9] == pytest.approx(result["angles"]["mc_deg"])


@pytest.mark.skipif(not os.getenv("SWISS_EPHE_PATH"), reason="official ephemeris data not configured")
@pytest.mark.parametrize("latitude", [75.0, -75.0])
def test_real_polar_location_switches_to_whole_sign(latitude):
    engine = SwissEngine(Path(os.environ["SWISS_EPHE_PATH"]))
    request = NatalRequest.model_validate({
        "schema_version": "1.0",
        "birth": {
            "local_date": "2000-01-01",
            "local_time": "21:00:00",
            "birth_time_known": True,
            "time_zone": "Asia/Tokyo",
            "utc_datetime": "2000-01-01T12:00:00Z",
            "latitude_deg": latitude,
            "longitude_deg": 0.0,
        },
    })
    result = engine.natal(request)
    assert result["calculation"]["house_system_used"] == "whole_sign"
    assert result["calculation"]["fallback_reason"] == "placidus_unavailable"
    assert len(result["houses"]["cusps_deg"]) == 12
