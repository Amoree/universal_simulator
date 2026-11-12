from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import Project, Requirement, Scenario
from app.schemas import ExtractionRequest, ProjectCreate, ProjectRead, RequirementInput, RequirementRead, ScenarioCreate, ScenarioRead, SimulationResult
from app.services.simulator import extract_requirements, simulate

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
Base.metadata.create_all(bind=engine)
app = FastAPI(title="MVP Requirements Simulator", version="0.2.0", docs_url=None, redoc_url=None)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def find_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def project_values(project: Project) -> list[dict]:
    return [{"key": item.key, "value": item.value} for item in project.requirements]


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/api/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@app.post("/api/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(name=payload.name.strip(), description=payload.description, original_requirements=payload.original_requirements)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.get("/api/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return find_project(db, project_id)


@app.post("/api/projects/{project_id}/requirements/extract")
def preview_extraction(project_id: int, payload: ExtractionRequest, db: Session = Depends(get_db)):
    find_project(db, project_id)
    return {"extracted": extract_requirements(payload.text), "processing": "local heuristic; confirm fields before saving"}


@app.put("/api/projects/{project_id}/requirements", response_model=list[RequirementRead])
def replace_requirements(project_id: int, items: list[RequirementInput], db: Session = Depends(get_db)):
    project = find_project(db, project_id)
    project.requirements.clear()
    db.flush()
    created = [Requirement(project_id=project_id, **item.model_dump()) for item in items]
    db.add_all(created)
    db.commit()
    for item in created:
        db.refresh(item)
    return created


@app.post("/api/projects/{project_id}/simulate", response_model=SimulationResult)
def simulate_project(project_id: int, db: Session = Depends(get_db)):
    project = find_project(db, project_id)
    result = simulate(project_values(project))
    return SimulationResult(project_id=project_id, **result)


@app.get("/api/projects/{project_id}/scenarios", response_model=list[ScenarioRead])
def list_scenarios(project_id: int, db: Session = Depends(get_db)):
    find_project(db, project_id)
    scenarios = db.query(Scenario).filter(Scenario.project_id == project_id).order_by(Scenario.id).all()
    return [ScenarioRead(id=item.id, project_id=item.project_id, name=item.name, description=item.description, overrides=json.loads(item.overrides_json or "{}")) for item in scenarios]


@app.post("/api/projects/{project_id}/scenarios", response_model=ScenarioRead, status_code=201)
def create_scenario(project_id: int, payload: ScenarioCreate, db: Session = Depends(get_db)):
    find_project(db, project_id)
    allowed = {"users", "daily_events", "retention_days", "peak_factor", "budget", "avg_event_size_kb", "compute_instances", "compute_unit_cost", "database_monthly_cost", "cache_monthly_cost", "queue_monthly_cost", "storage_cost_per_gb", "network_monthly_cost"}
    unknown = set(payload.overrides) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported override keys: {', '.join(sorted(unknown))}")
    scenario = Scenario(project_id=project_id, name=payload.name.strip(), description=payload.description, overrides_json=json.dumps(payload.overrides))
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return ScenarioRead(id=scenario.id, project_id=project_id, name=scenario.name, description=scenario.description, overrides=payload.overrides)


@app.post("/api/projects/{project_id}/scenarios/{scenario_id}/simulate", response_model=SimulationResult)
def simulate_scenario(project_id: int, scenario_id: int, db: Session = Depends(get_db)):
    project = find_project(db, project_id)
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id, Scenario.project_id == project_id).first()
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    result = simulate(project_values(project), json.loads(scenario.overrides_json or "{}"))
    return SimulationResult(project_id=project_id, scenario_id=scenario_id, **result)
