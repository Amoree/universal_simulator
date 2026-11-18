from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, get_db


SAME_ORIGIN = {"Origin": "http://testserver"}
PLAN_KEY = "__solution_plan_v1__"


@pytest.fixture
def client():
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    testing_session = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    def override_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, headers=SAME_ORIGIN) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def register(client: TestClient, username: str) -> TestClient:
    response = client.post("/api/auth/register", json={"username": username, "password": "correct-horse-42"})
    assert response.status_code == 201
    return client


def test_solution_plan_round_trips_with_project_requirements(client: TestClient):
    owner = register(client, "plan_owner")
    created = owner.post("/api/projects", json={"name": "Appointment MVP", "original_requirements": "Patients can book visits."})
    assert created.status_code == 201
    project_id = created.json()["id"]

    plan = {
        "projectId": project_id,
        "project": "Appointment MVP",
        "raw": "Patients can book visits.",
        "architecture": ["Responsive web client", "Application API", "Relational database"],
        "tickets": [["Booking flow", "Patients can book a visit", "Story", "High", "A patient can book an available time."]],
    }
    requirement_rows = [
        {
            "category": "solution_plan",
            "key": PLAN_KEY,
            "value": json.dumps(plan),
            "source_text": "Generated locally by the project build planner",
            "confidence": "medium",
            "confirmed": False,
        }
    ]
    saved = owner.put(f"/api/projects/{project_id}/requirements", json=requirement_rows)
    assert saved.status_code == 200
    assert saved.json()[0]["key"] == PLAN_KEY

    loaded = owner.get(f"/api/projects/{project_id}/requirements")
    assert loaded.status_code == 200
    record = next(item for item in loaded.json() if item["key"] == PLAN_KEY)
    assert json.loads(record["value"]) == plan


def test_solution_plan_obeys_project_membership_and_editor_permissions(client: TestClient):
    owner = register(client, "plan_owner")
    project = owner.post("/api/projects", json={"name": "Private plan"}).json()
    project_id = project["id"]
    plan_row = {
        "category": "solution_plan",
        "key": PLAN_KEY,
        "value": json.dumps({"project": "Private plan", "tickets": []}),
        "confidence": "medium",
        "confirmed": False,
    }
    assert owner.put(f"/api/projects/{project_id}/requirements", json=[plan_row]).status_code == 200

    viewer = register(TestClient(app, headers=SAME_ORIGIN), "plan_viewer")
    assert viewer.get(f"/api/projects/{project_id}/requirements").status_code == 404
    assert owner.post(f"/api/projects/{project_id}/members", json={"username": "plan_viewer", "role": "viewer"}).status_code == 201
    assert viewer.get(f"/api/projects/{project_id}/requirements").status_code == 200
    assert viewer.put(f"/api/projects/{project_id}/requirements", json=[plan_row]).status_code == 403

    editor = register(TestClient(app, headers=SAME_ORIGIN), "plan_editor")
    assert owner.post(f"/api/projects/{project_id}/members", json={"username": "plan_editor", "role": "editor"}).status_code == 201
    updated = {**plan_row, "value": json.dumps({"project": "Private plan", "tickets": [{"summary": "Revised"}]})}
    assert editor.put(f"/api/projects/{project_id}/requirements", json=[updated]).status_code == 200
