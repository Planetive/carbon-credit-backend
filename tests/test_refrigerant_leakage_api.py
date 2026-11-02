"""HTTP contract for EPA refrigerant leakage. No database connection and no writes."""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.db import get_db
from fastapi_app.routers import calc as calc_routes
from fastapi_app.routers.deps import require_org_context
from tests.test_refrigerant_leakage import _blend_row, _sheet

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class SpySession:
    def __init__(self):
        self.added = []
        self.committed = False
        self.flushed = False
        self.queries = 0

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True

    def flush(self):
        self.flushed = True

    def rollback(self):
        return None

    def close(self):
        return None

    def query(self, *args, **kwargs):
        self.queries += 1
        raise AssertionError("the calculation endpoint must not query through the request session")


def _ctx():
    user = User(id=uuid.uuid4(), email="refrigerant@example.com", password_hash="x")
    return OrgContext(user=user, organization_id=ORG_ID, role="admin")


def _client(monkeypatch, session, sheets=None):
    loaded = [_sheet()] if sheets is None else sheets
    monkeypatch.setattr(calc_routes, "load_refrigerant_factor_sheets", lambda db: loaded)
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _post(client, **overrides):
    body = {
        "method": "leakage_record",
        "gas": "R-404A",
        "leakage_kg": "2",
        "gwp": "1",
        "emissions_kg_co2e": "0",
        "emissions_tco2e": "0",
        "factor": "3922",
    }
    body.update(overrides)
    return client.post("/api/v1/calc/epa/refrigerant-leakage", json=body)


def _assert_no_write(session):
    assert session.added == []
    assert session.committed is False
    assert session.flushed is False
    assert session.queries == 0


def _assert_rejected(response):
    assert response.status_code == 422
    payload = response.json()
    assert "emissions_tco2e" not in payload
    assert "emissions_kg_co2e" not in payload
    assert payload.get("emissions_tco2e") is None
    assert payload.get("detail")


def test_blend_calculations_return_the_engine_result(monkeypatch):
    session = SpySession()
    client = _client(monkeypatch, session)

    r404a = _post(client)
    assert r404a.status_code == 200
    body = r404a.json()
    assert body["success"] is True
    assert body["method"] == "leakage_record"
    assert body["refrigerant"] == "R-404A"
    assert body["gwp"] == "3943"
    assert body["leakage_kg"] == "2"
    assert body["emissions_kg_co2e"] == "7886"
    assert body["emissions_tco2e"] == "7.886"
    assert body["dataset_code"] == "epa_refrigerant_gwp"
    assert body["dataset_id"]
    assert body["factor_row_id"] == "row-r404a"
    assert body["factor_attribute"] == "100-year GWP"
    assert body["accounting"]["version"] == "epa_refrigerant_v1"
    assert "Table 12" in body["gwp_publication"]
    assert body["gwp"] != "1"

    r410a = _post(client, gas="R-410A", leakage_kg="1")
    assert r410a.status_code == 200
    assert r410a.json()["gwp"] == "1924"
    assert r410a.json()["emissions_tco2e"] == "1.924"
    assert r410a.json()["factor_row_id"] == "row-r410a"
    _assert_no_write(session)


def test_pure_hfc134a_does_not_use_a_blend_row(monkeypatch):
    session = SpySession()
    client = _client(monkeypatch, session)
    response = _post(client, gas="R-134a", leakage_kg="2")
    assert response.status_code == 200
    body = response.json()
    assert body["refrigerant"] == "HFC-134a"
    assert body["gwp"] == "1300"
    assert body["emissions_tco2e"] == "2.6"
    assert body["dataset_id"] is None
    assert body["factor_row_id"] is None
    assert "Table 11" in body["table11_reference"]
    _assert_no_write(session)


def test_pure_hfc_succeeds_when_the_blend_dataset_is_unavailable(monkeypatch):
    session = SpySession()
    missing = [
        {
            "dataset_code": "epa_refrigerant_gwp",
            "is_active": True,
            "load_error": (
                "Authoritative dataset epa_refrigerant_gwp is missing or inactive. "
                "No other factor edition is substituted."
            ),
            "rows": [],
        }
    ]
    client = _client(monkeypatch, session, sheets=missing)
    pure = _post(client, gas="HFC-134a", leakage_kg="1")
    assert pure.status_code == 200
    assert pure.json()["gwp"] == "1300"
    assert pure.json()["emissions_tco2e"] == "1.3"
    assert pure.json()["dataset_id"] is None

    blend = _post(client, gas="R-404A", leakage_kg="2")
    _assert_rejected(blend)
    assert "missing or inactive" in blend.json()["detail"]
    _assert_no_write(session)


def test_estimated_leakage_requires_an_explicit_rate(monkeypatch):
    session = SpySession()
    client = _client(monkeypatch, session)
    estimated = _post(
        client,
        method="estimated_leakage",
        gas="R-410A",
        leakage_kg=None,
        charge_kg="10",
        leakage_rate_percent="10",
        equipment_type="packaged AC",
    )
    assert estimated.status_code == 200
    body = estimated.json()
    assert body["method"] == "estimated_leakage"
    assert body["leakage_kg"] == "1"
    assert body["charge_kg"] == "10"
    assert body["leakage_rate_percent"] == "10"
    assert body["leakage_rate_source"] == "user_assumption"
    assert body["equipment_type"] == "packaged AC"
    assert body["emissions_tco2e"] == "1.924"

    missing_rate = client.post(
        "/api/v1/calc/epa/refrigerant-leakage",
        json={"method": "estimated_leakage", "gas": "R-410A", "charge_kg": "10"},
    )
    _assert_rejected(missing_rate)
    assert "leakage_rate_percent" in str(missing_rate.json()["detail"])
    _assert_no_write(session)


def test_unsupported_zero_gwp_and_conflicting_rows_are_422(monkeypatch):
    session = SpySession()
    client = _client(monkeypatch, session)

    unknown = _post(client, gas="R-999")
    _assert_rejected(unknown)
    assert "not a supported refrigerant" in unknown.json()["detail"]

    zero = _post(client, gas="R-406A")
    _assert_rejected(zero)
    assert "zero-GWP" in zero.json()["detail"]

    monkeypatch.setattr(
        calc_routes,
        "load_refrigerant_factor_sheets",
        lambda db: [
            _sheet(
                rows=[
                    _blend_row("R-404A", "3943", "44% HFC-125, 4% HFC-134a, 52% HFC-143a", "row-a"),
                    _blend_row("R-404A", "3943", "44% HFC-125, 4% HFC-134a, 52% HFC-143a", "row-b"),
                ]
            )
        ],
    )
    conflict = _post(client, gas="R-404A", leakage_kg="2")
    _assert_rejected(conflict)
    assert "More than one" in conflict.json()["detail"]
    _assert_no_write(session)


def test_browser_gwp_does_not_change_the_result(monkeypatch):
    session = SpySession()
    client = _client(monkeypatch, session)
    response = _post(client, gwp="1", emissions_tco2e="0", emissions_kg_co2e="1", factor="3922")
    assert response.status_code == 200
    assert response.json()["gwp"] == "3943"
    assert response.json()["emissions_kg_co2e"] == "7886"
    assert response.json()["emissions_tco2e"] == "7.886"
    _assert_no_write(session)


def test_unauthenticated_request_is_rejected():
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/epa/refrigerant-leakage",
        json={"method": "leakage_record", "gas": "R-404A", "leakage_kg": "2"},
    )
    assert response.status_code in (401, 403)


def test_invalid_json_is_rejected(monkeypatch):
    client = _client(monkeypatch, SpySession())
    response = client.post(
        "/api/v1/calc/epa/refrigerant-leakage",
        content=b'{"method": "leakage_record", ',
        headers={"content-type": "application/json"},
    )
    _assert_rejected(response)
