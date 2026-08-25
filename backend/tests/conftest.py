from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.seed import DEMO_USERS, PRIMARY_PATIENT_ID


@pytest.fixture()
def app():
    application = create_app(database_url="sqlite://", seed_data=True)
    yield application
    application.state.database.engine.dispose()


@pytest.fixture()
def client(app) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def identities() -> dict[str, str]:
    return DEMO_USERS.copy()


@pytest.fixture()
def patient_id() -> str:
    return PRIMARY_PATIENT_ID


def auth(user_id: str) -> dict[str, str]:
    return {"X-Demo-User": user_id}


def workspace(client: TestClient, user_id: str, patient_id: str) -> dict:
    response = client.get(
        f"/api/v1/patients/{patient_id}/workspace",
        headers=auth(user_id),
    )
    assert response.status_code == 200, response.text
    return response.json()


def entry_named(payload: dict, title: str) -> dict:
    return next(item for item in payload["entries"] if item["title"] == title)
