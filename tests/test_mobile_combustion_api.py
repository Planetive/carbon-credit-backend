"""HTTP contract for EPA mobile combustion. No database connection and no writes."""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.auth_models import User
from fastapi_app.auth_org import OrgContext
from fastapi_app.db import get_db
from fastapi_app.routers import calc as calc_routes
from fastapi_app.routers.deps import require_org_context
from tests.test_mobile_combustion import _sheets

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class SpySession:
    def __init__(self):
        self.added = []
        self.committed = False
        self.flushed = False

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


def _ctx():
    user = User(id=uuid.uuid4(), email="mobile@example.com", password_hash="x")
    return OrgContext(user=user, organization_id=ORG_ID, role="admin")


def _client(monkeypatch, session):
    monkeypatch.setattr(calc_routes, "load_mobile_factor_sheets", lambda db: _sheets())
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_org_context] = lambda: _ctx()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _post(client, **overrides):
    body = {
        "road_class": "on_road",
        "vehicle_type": "Passenger Cars",
        "fuel_type": "Motor Gasoline",
        "fuel_quantity": "10",
        "fuel_unit": "gallon",
        "distance": "100",
        "distance_unit": "mile",
        "model_year": 2020,
        "gwp_version": "AR5",
        "factor": "1",
        "emissions": "0",
        "total_t_co2e": "999",
    }
    body.update(overrides)
    return client.post("/api/v1/calc/epa/mobile", json=body)


def test_gasoline_diesel_cng_and_non_road_return_the_engine_result(monkeypatch):
    session = SpySession()
    client = _client(monkeypatch, session)

    gasoline = _post(client)
    assert gasoline.status_code == 200
    body = gasoline.json()
    assert body["success"] is True
    assert body["total_t_co2e"] == "0.088358"
    assert body["biogenic_co2_t"] == "0"
    assert body["gases"]["co2"]["mass_kg"] == "87.8"
    assert body["gases"]["ch4"]["mass_kg"] == "0.001"
    assert body["gases"]["n2o"]["mass_kg"] == "0.002"
    assert body["factors"]["ch4"]["factor_row_id"] == "gas-2020"
    assert body["factors"]["co2"]["dataset_code"] == "mobile_combustion"
    assert body["vehicle_type"] == "Passenger Cars"
    assert body["fuel"] == "Motor Gasoline"
    assert body["model_year"] == "2020"
    assert body["accounting"]["gwp_version"] == "AR5"
    assert body["accounting"]["methodology"]
    assert body["factors"]["co2"]["value"] == "8.78"

    diesel = _post(
        client,
        vehicle_type="Heavy-Duty Trucks",
        fuel_type="Diesel Fuel",
        fuel_quantity="1",
        distance="10",
        model_year=2010,
    )
    assert diesel.status_code == 200
    assert diesel.json()["gases"]["co2"]["mass_kg"] == "10.21"
    assert diesel.json()["factors"]["ch4"]["dataset_code"] == "on_road_diesel_alt_fuel"

    cng = _post(
        client,
        vehicle_type="Light-Duty Cars",
        fuel_type="Compressed Natural Gas",
        fuel_quantity="100",
        fuel_unit="scf",
        distance="10",
        model_year=None,
    )
    assert cng.status_code == 200
    assert cng.json()["gases"]["co2"]["mass_kg"] == "5.444"
    assert cng.json()["fuel_unit"] == "scf"

    non_road = _post(
        client,
        road_class="non_road",
        vehicle_type="Agricultural Equipment",
        fuel_type="Diesel Fuel",
        fuel_quantity="5",
        distance=None,
        model_year=None,
    )
    assert non_road.status_code == 200
    assert non_road.json()["total_kg_co2e"] == "51.72"
    assert non_road.json()["factors"]["n2o"]["dataset_code"] == "non_road_vehicle"
    assert session.added == []
    assert session.committed is False
    assert session.flushed is False


def test_missing_ambiguous_and_incompatible_units_are_unsuccessful(monkeypatch):
    client = _client(monkeypatch, SpySession())

    missing = _post(client, vehicle_type="Motorcycles")
    assert missing.status_code == 422
    assert missing.json()["detail"]
    assert "total_t_co2e" not in missing.json()

    gasoline_rows = [
        row
        for row in _sheets()
        if row["dataset_code"] == "on_road_gasoline"
    ][0]["rows"]
    # 2014 matches only 2010-2014 in the fixture. Add an overlapping row through the loader.
    overlap = list(gasoline_rows) + [
        {
            "Vehicle Type": "Passenger Cars",
            "Model Year": "2014-2016",
            "CH4 Factor (g CH4 / vehicle-mile)": "0.09",
            "N2O Factor (g N2O / vehicle-mile)": "0.09",
        }
    ]
    monkeypatch.setattr(
        calc_routes,
        "load_mobile_factor_sheets",
        lambda db: _sheets(on_road_gasoline=overlap),
    )
    ambiguous = _post(client, model_year=2014)
    assert ambiguous.status_code == 422
    assert "more than one" in ambiguous.json()["detail"]

    wrong_unit = _post(
        client,
        vehicle_type="Light-Duty Cars",
        fuel_type="Compressed Natural Gas",
        fuel_unit="gallon",
        model_year=None,
    )
    assert wrong_unit.status_code == 422
    assert "scf" in wrong_unit.json()["detail"]
    assert "total_t_co2e" not in wrong_unit.json()


def test_unauthenticated_request_is_rejected():
    app = FastAPI()
    app.include_router(calc_routes.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.post(
        "/api/v1/calc/epa/mobile",
        json={
            "road_class": "on_road",
            "vehicle_type": "Passenger Cars",
            "fuel_type": "Motor Gasoline",
            "fuel_quantity": "10",
            "fuel_unit": "gallon",
            "distance": "100",
            "distance_unit": "mile",
            "model_year": 2020,
        },
    )
    assert response.status_code in (401, 403)


def test_request_body_validation_rejects_incomplete_input(monkeypatch):
    client = _client(monkeypatch, SpySession())
    missing_fuel = client.post(
        "/api/v1/calc/epa/mobile",
        json={"road_class": "on_road", "vehicle_type": "Passenger Cars", "fuel_quantity": "10"},
    )
    assert missing_fuel.status_code == 422

    bad_quantity = _post(client, fuel_quantity="not-a-number")
    assert bad_quantity.status_code == 422
