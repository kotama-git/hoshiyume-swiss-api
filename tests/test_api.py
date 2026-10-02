import pytest
import swisseph as swe
from fastapi.testclient import TestClient

from swiss_api.calculation import EphemerisUnavailable, SwissEngine, major_aspects
from swiss_api.main import app, get_engine
from swiss_api.models import NatalRequest
from swiss_api.rules import current_rules, rules_sha256


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
    monkeypatch.setenv("SOURCE_CODE_URL", "https://example.test/source/tree/test-commit")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_without_ephemeris(client, monkeypatch):
    monkeypatch.delenv("SWISS_EPHE_PATH", raising=False)
    response = client.get("/health")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "not_ready"
    assert result["ephemeris_files_configured"] is False
    assert result["source_offer_configured"] is True
    assert result["engine_version"] is None
    assert result["wrapper_version"] is None
    assert result["ephemeris_dataset_sha256"] is None
    assert result["rules_version"] == current_rules()["rules_version"]
    assert result["rules_sha256"] == rules_sha256()
    assert result["body_ids"] == [body["id"] for body in current_rules()["bodies"]]
    assert result["aspect_ids"] == [aspect["id"] for aspect in current_rules()["aspects"]]


def test_health_not_ready_without_service_token(client, tmp_path, monkeypatch):
    _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setenv("SWISS_EPHE_PATH", str(tmp_path))
    monkeypatch.delenv("SWISS_API_TOKEN")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "not_ready"


def test_health_not_ready_without_source_offer(client, tmp_path, monkeypatch):
    _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setenv("SWISS_EPHE_PATH", str(tmp_path))
    monkeypatch.delenv("SOURCE_CODE_URL")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "not_ready"
    assert response.json()["source_offer_configured"] is False


def test_every_response_offers_corresponding_source(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["license"] == "AGPL-3.0-or-later"
    assert response.headers["link"] == (
        '<https://example.test/source/tree/test-commit>; rel="source"'
    )
    redirect = client.get("/source", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://example.test/source/tree/test-commit"


@pytest.mark.parametrize(
    "value",
    [
        "http://example.test/source",
        "https://user:secret@example.test/source",
        "https://example.test/source#fragment",
    ],
)
def test_invalid_source_offer_is_rejected(client, monkeypatch, value):
    monkeypatch.setenv("SOURCE_CODE_URL", value)
    response = client.get("/health")
    assert response.json()["source_offer_configured"] is False
    assert client.get("/source", follow_redirects=False).status_code == 503


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
    assert major_aspects(bodies)[0]["aspect_type"] == "conjunction"
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
    assert len(result["bodies"]) == 12
    assert result["bodies"][-2]["id"] == "north_node"
    assert result["bodies"][-1]["id"] == "south_node"
    assert result["angles"]["descendant_deg"] == 300
    assert result["angles"]["ic_deg"] == 210
    assert result["calculation"]["rules_version"] == current_rules()["rules_version"]
    assert result["calculation"]["reference_time_status"] == "birth_time"


def test_standard_rules_include_every_formal_aspect_and_orb():
    rules = current_rules()
    for aspect in rules["aspects"]:
        bodies = [{"id": "sun", "longitude_deg": 0}, {"id": "moon", "longitude_deg": aspect["angle_deg"] + aspect["orb_deg"]}]
        found = major_aspects(bodies)
        assert found[0]["aspect_type"] == aspect["id"]
        assert found[0]["orb_deg"] == aspect["orb_deg"]


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


def test_cross_aspects_keep_chart_sides_and_do_not_add_internal_pairs():
    from swiss_api.calculation import cross_aspects
    first = [{"id": "sun", "longitude_deg": 0}, {"id": "moon", "longitude_deg": 120}]
    second = [{"id": "sun", "longitude_deg": 60}]
    result = cross_aspects(first, second, "synastry")
    assert len(result) == 2
    assert all(a["body1"].startswith("first:") and a["body2"] == "second:sun" for a in result)
    assert all(a["context"] == "synastry" for a in result)


@pytest.mark.parametrize("path", ["sky", "transit", "synastry"])
def test_extension_routes_require_authentication(client, path):
    assert client.post("/" + path, json={}).status_code == 401


def test_sky_has_no_invented_geographic_houses(client, tmp_path, monkeypatch):
    engine = _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(swe, "houses_ex", lambda *args: pytest.fail("houses must not be computed without a location"))
    app.dependency_overrides[get_engine] = lambda: engine
    response = client.post("/sky", json={"schema_version": "1.0", "utc_datetime": "2026-10-02T03:00:00Z"}, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 200
    chart = response.json()
    assert chart["chart_type"] == "sky"
    assert chart["angles"] is None and chart["houses"]["cusps_deg"] is None
    assert all(b["position_status"] == "exact" and b["house"] is None for b in chart["bodies"])
    assert chart["calculation"]["reference_time_status"] == "target_time"


def test_transit_uses_selected_instant_and_cross_chart_aspects(client, tmp_path, monkeypatch):
    engine = _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(swe, "houses_ex", lambda *args: ([float(i * 30) for i in range(12)], [120.0, 30.0]))
    app.dependency_overrides[get_engine] = lambda: engine
    body = {"schema_version": "1.0", "natal": KNOWN, "target": {"schema_version": "1.0", "utc_datetime": "2030-01-01T03:00:00Z"}}
    response = client.post("/transit", json=body, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 200
    result = response.json()
    assert result["second"]["calculation"]["reference_utc_datetime"] == "2030-01-01T03:00:00Z"
    assert all(a["body1"].startswith("first:") and a["body2"].startswith("second:") for a in result["aspects"])


def test_synastry_unknown_time_is_reference_only(client, tmp_path, monkeypatch):
    engine = _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(swe, "houses_ex", lambda *args: ([float(i * 30) for i in range(12)], [120.0, 30.0]))
    app.dependency_overrides[get_engine] = lambda: engine
    unknown = {**KNOWN, "birth": {**KNOWN["birth"], "birth_time_known": False, "local_time": None, "utc_datetime": None}}
    response = client.post("/synastry", json={"schema_version": "1.0", "first": KNOWN, "second": unknown}, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 200
    result = response.json()
    assert result["aspects"] == []
    assert result["second"]["angles"] is None
    assert "unknown_birth_time_no_firm_cross_aspects" in result["warnings"]


@pytest.mark.parametrize("instant", ["2026-10-02T12:00:00", "2026-10-02T12:00:00+09:00", "2400-01-01T00:00:00Z"])
def test_sky_rejects_invalid_instant(client, instant):
    response = client.post("/sky", json={"schema_version": "1.0", "utc_datetime": instant}, headers={"Authorization": "Bearer test-service-secret"})
    assert response.status_code == 422


def test_transit_reuses_saved_natal_and_rejects_outdated_calculation(tmp_path, monkeypatch):
    from swiss_api.models import TransitRequest
    engine = _mock_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(swe, "houses_ex", lambda *args: ([float(i * 30) for i in range(12)], [120.0, 30.0]))
    saved = engine.natal(NatalRequest.model_validate(KNOWN))
    target = {"schema_version": "1.0", "utc_datetime": "2026-10-02T03:00:00Z"}
    result = engine.transit(TransitRequest.model_validate({"schema_version":"1.0", "natal":saved, "target":target}))
    assert result["first"]["bodies"] == saved["bodies"]
    saved["calculation"]["rules_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="version does not match"):
        engine.transit(TransitRequest.model_validate({"schema_version":"1.0", "natal":saved, "target":target}))
