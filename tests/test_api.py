import pytest
import swisseph as swe
from fastapi.testclient import TestClient

from swiss_api.calculation import EphemerisUnavailable, SwissEngine, major_aspects
from swiss_api.main import app, get_engine
from swiss_api.models import NatalRequest


KNOWN = {
    "schema_version": "1.0",
    "birth": {
        "local_date": "1994-09-08",
        "local_time": "08:30:00",
        "birth_time_known": True,
        "time_zone": "Asia/Tokyo",
        "utc_datetime": "1994-09-07T23:30:00Z",
        "latitude_deg": 35.68,
        "longitude_deg": 139.76,
    },
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SWISS_API_TOKEN", "test-service-secret")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_without_ephemeris(client, monkeypatch):
    monkeypatch.delenv("SWISS_EPHE_PATH", raising=False)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "not_ready",
        "ephemeris_files_configured": False,
        "engine_version": None,
        "wrapper_version": None,
        "ephemeris_dataset_sha256": None,
        "rules_version": "natal_v1",
    }


def test_natal_requires_service_authentication(client):
    assert client.post("/natal", json=KNOWN).status_code == 401
    assert client.post("/natal", json=KNOWN, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_natal_rejects_missing_ephemeris_data(client, monkeypatch):
    monkeypatch.delenv("SWISS_EPHE_PATH", raising=False)
    response = client.post("/natal", json=KNOWN, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 503


def test_known_time_requires_consistent_utc(client):
    request = {**KNOWN, "birth": {**KNOWN["birth"], "utc_datetime": "1994-09-08T00:30:00Z"}}
    response = client.post("/natal", json=request, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 422


def test_known_time_requires_utc_offset():
    request = {**KNOWN, "birth": {**KNOWN["birth"], "utc_datetime": "1994-09-08T08:30:00+09:00"}}
    with pytest.raises(ValueError):
        NatalRequest.model_validate(request)


def test_unknown_time_must_not_contain_a_fabricated_time():
    birth = {**KNOWN["birth"], "birth_time_known": False}
    with pytest.raises(ValueError):
        NatalRequest.model_validate({**KNOWN, "birth": birth})


def test_major_aspects_include_orb_boundary():
    bodies = [{"id": "sun", "longitude_deg": 0}, {"id": "moon", "longitude_deg": 8}]
    assert major_aspects(bodies)[0]["type"] == "conjunction"
    bodies[1]["longitude_deg"] = 8.001
    assert major_aspects(bodies) == []


def _mock_engine(tmp_path, monkeypatch):
    (tmp_path / "sepl_18.se1").write_bytes(b"test-only-not-an-ephemeris")
    (tmp_path / "semo_18.se1").write_bytes(b"test-only-not-an-ephemeris")
    engine = SwissEngine(tmp_path)
    assert engine.ready
    monkeypatch.setattr(swe, "set_ephe_path", lambda _: None)
    monkeypatch.setattr(
        swe, "calc_ut",
        lambda jd, body, flags: ((float(body * 20), 0.0, 1.0, 1.0, 0.0, 0.0), swe.FLG_SWIEPH | swe.FLG_SPEED),
    )
    return engine


def test_natal_uses_placidus_and_returns_versioned_json(client, tmp_path, monkeypatch):
    engine = _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(
        swe, "houses_ex",
        lambda jd, lat, lon, system: ([float(i * 30) for i in range(12)], [120.0, 30.0]),
    )
    app.dependency_overrides[get_engine] = lambda: engine
    response = client.post("/natal", json=KNOWN, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 200
    result = response.json()
    assert result["schema_version"] == "1.0"
    assert result["calculation"]["house_system_used"] == "placidus"
    assert result["houses"]["status"] == "computed"
    assert len(result["bodies"]) == 10
    assert result["calculation"]["reference_time_status"] == "birth_time"


def test_polar_placidus_error_switches_to_whole_sign(client, tmp_path, monkeypatch):
    engine = _mock_engine(tmp_path, monkeypatch)

    def houses(jd, lat, lon, system):
        if system == b"P":
            raise swe.Error("Placidus unavailable")
        assert system == b"W"
        return [float(i * 30) for i in range(12)], [120.0, 30.0]

    monkeypatch.setattr(swe, "houses_ex", houses)
    app.dependency_overrides[get_engine] = lambda: engine
    request = {**KNOWN, "birth": {**KNOWN["birth"], "latitude_deg": 75.0}}
    response = client.post("/natal", json=request, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 200
    calculation = response.json()["calculation"]
    assert calculation["house_system_requested"] == "placidus"
    assert calculation["house_system_used"] == "whole_sign"
    assert calculation["fallback_reason"] == "placidus_unavailable"
    assert "house_system_changed_to_whole_sign" in response.json()["warnings"]


def test_unknown_time_has_no_angles_houses_or_firm_aspects(client, tmp_path, monkeypatch):
    engine = _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(swe, "houses_ex", lambda *args: pytest.fail("houses must not be calculated"))
    app.dependency_overrides[get_engine] = lambda: engine
    request = {**KNOWN, "birth": {**KNOWN["birth"], "birth_time_known": False, "local_time": None, "utc_datetime": None}}
    response = client.post("/natal", json=request, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 200
    result = response.json()
    assert result["angles"] is None
    assert result["houses"]["status"] == "unavailable"
    assert result["aspects"] == []
    assert result["calculation"]["reference_time_status"] == "local_noon_not_birth_time"


def test_geographic_pole_has_no_houses(client, tmp_path, monkeypatch):
    engine = _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(swe, "houses_ex", lambda *args: pytest.fail("pole houses must not be calculated"))
    app.dependency_overrides[get_engine] = lambda: engine
    request = {**KNOWN, "birth": {**KNOWN["birth"], "latitude_deg": 90.0}}
    response = client.post("/natal", json=request, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 200
    assert response.json()["angles"] is None
    assert response.json()["houses"]["status"] == "unavailable"
    assert "geographic_pole_houses_unavailable" in response.json()["warnings"]


def test_rejects_ephemeris_engine_fallback(tmp_path, monkeypatch):
    engine = _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(
        swe, "calc_ut",
        lambda jd, body, flags: ((0.0, 0.0, 1.0, 1.0, 0.0, 0.0), swe.FLG_MOSEPH),
    )
    with pytest.raises(EphemerisUnavailable):
        engine.natal(NatalRequest.model_validate(KNOWN))
