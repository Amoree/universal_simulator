from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, get_db


@pytest.fixture
def client():
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    # In the client fixture:
with TestClient(app, headers={"Origin": "http://testserver"}) as test_client:
    yield test_client

# In test_auth_project_flow_and_ownership_sharing:
guest = register(
    TestClient(app, headers={"Origin": "http://testserver"}),
    "guest_user",
)

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def register(client: TestClient, username: str) -> TestClient:
    response = client.post("/api/auth/register", json={"username": username, "password": "correct-horse-42"})
    assert response.status_code == 201
    return client


def test_auth_project_flow_and_ownership_sharing(client: TestClient):
    owner = register(client, "owner_one")
    created = owner.post("/api/projects", json={"name": "MVP Alpha", "description": "test"})
    assert created.status_code == 201
    project_id = created.json()["id"]

    assert owner.get("/api/projects").json()[0]["name"] == "MVP Alpha"
    assert owner.put(f"/api/projects/{project_id}/requirements", json=[{"key": "daily_events", "value": "86400"}]).status_code == 200
    result = owner.post(f"/api/projects/{project_id}/simulate")
    assert result.status_code == 200
    assert result.json()["average_rps"] == 1.0

    guest = register(TestClient(app), "guest_user")
    assert guest.get(f"/api/projects/{project_id}").status_code == 404
    assert guest.post(f"/api/projects/{project_id}/members", json={"username": "owner_one", "role": "viewer"}).status_code == 403

    shared = owner.post(f"/api/projects/{project_id}/members", json={"username": "guest_user", "role": "viewer"})
    assert shared.status_code == 201
    assert guest.get(f"/api/projects/{project_id}").status_code == 200
    assert guest.put(f"/api/projects/{project_id}/requirements", json=[]).status_code == 403
    assert owner.delete(f"/api/projects/{project_id}/members/{guest.get('/api/auth/me').json()['id']}").status_code == 204
    assert guest.get(f"/api/projects/{project_id}").status_code == 404


def test_auth_validation_logout_and_session_expiry(client: TestClient):
    assert client.post("/api/auth/register", json={"username": "ab", "password": "short"}).status_code == 422
    register(client, "caseuser")
    assert client.post("/api/auth/register", json={"username": "CASEUSER", "password": "correct-horse-42"}).status_code == 409
    assert client.post("/api/auth/login", json={"username": "caseuser", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_missing_or_cross_origin_protected_requests(client: TestClient):
    assert client.get("/api/projects").status_code == 401
    client.post("/api/auth/register", json={"username": "originuser", "password": "correct-horse-42"})
    assert client.post("/api/projects", headers={"Origin": "https://evil.example"}, json={"name": "Nope"}).status_code == 403
