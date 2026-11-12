from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import AuthSession, Project, ProjectMember, Requirement, Scenario, User
from app.schemas import AuthResponse, ExtractionRequest, ProjectCreate, ProjectMemberRead, ProjectRead, ProjectShareCreate, RequirementInput, RequirementRead, ScenarioCreate, ScenarioRead, SimulationResult, UserCreate, UserLogin, UserRead
from app.services.simulator import extract_requirements, simulate

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
SESSION_COOKIE = "sim_session"
SESSION_DAYS = 14
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
app = FastAPI(title="MVP Requirements Simulator", version="0.3.0", docs_url=None, redoc_url=None)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_schema() -> None:
    """Create new tables and safely add nullable ownership to older SQLite databases."""
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        columns = {column["name"] for column in inspect(engine).get_columns("projects")}
        if "user_id" not in columns:
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE projects ADD COLUMN user_id INTEGER REFERENCES users(id)")


@app.on_event("startup")
def startup() -> None:
    migrate_schema()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=actual_salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt${actual_salt.hex()}${derived.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        candidate = _hash_password(password, bytes.fromhex(salt_hex)).split("$", 2)[2]
        return hmac.compare_digest(candidate, digest_hex)
    except (ValueError, TypeError):
        return False


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _set_session(response: Response, db: Session, user: User) -> None:
    raw_token = secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user.id, token_hash=_token_digest(raw_token), expires_at=datetime.utcnow() + timedelta(days=SESSION_DAYS)))
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=COOKIE_SECURE, samesite="strict")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_digest(raw_token)))
    if session is None or session.expires_at <= datetime.utcnow():
        if session is not None:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired; please sign in again")
    return session.user


def require_project(db: Session, project_id: int, user: User, write: bool = False) -> tuple[Project, str]:
    project = db.get(Project, project_id)
    if project is None or project.user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.user_id == user.id:
        return project, "owner"
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user.id))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if write and member.role != "editor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Editor access is required")
    return project, member.role


@app.middleware("http")
async def same_origin_cookie_protection(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        has_cookie = bool(request.cookies.get(SESSION_COOKIE))
        if origin:
            parsed = urlparse(origin)
            expected = (request.url.scheme, request.url.netloc)
            if (parsed.scheme, parsed.netloc) != expected:
                return Response("Cross-origin request rejected", status_code=403)
        elif has_cookie:
            return Response("Origin header required for authenticated browser requests", status_code=403)
    return await call_next(request)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
def register(payload: UserCreate, response: Response, db: Session = Depends(get_db)):
    username = payload.username.lower()
    user = User(username=username, password_hash=_hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
        _set_session(response, db, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username is already registered") from None
    return {"user": {"id": user.id, "username": user.username}}


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: UserLogin, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username.lower()))
    if user is None or not _verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    # Remove expired records, but keep other devices' valid sessions intact.
    db.query(AuthSession).filter(AuthSession.expires_at <= datetime.utcnow()).delete(synchronize_session=False)
    _set_session(response, db, user)
    db.commit()
    return {"user": {"id": user.id, "username": user.username}}


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_digest(token)))
        if session:
            db.delete(session)
            db.commit()
    _clear_session_cookie(response)
    response.status_code = 204
    return response


@app.get("/api/auth/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username}


@app.get("/api/projects", response_model=list[ProjectRead])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned = db.scalars(select(Project).where(Project.user_id == user.id).order_by(Project.updated_at.desc())).all()
    shared = db.scalars(select(Project).join(ProjectMember).where(ProjectMember.user_id == user.id).order_by(Project.updated_at.desc())).all()
    return list({project.id: project for project in [*owned, *shared]}.values())


@app.post("/api/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = Project(name=payload.name.strip(), description=payload.description, original_requirements=payload.original_requirements, user_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.get("/api/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _ = require_project(db, project_id, user)
    return project


@app.put("/api/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _ = require_project(db, project_id, user, write=True)
    project.name = payload.name.strip()
    project.description = payload.description
    project.original_requirements = payload.original_requirements
    db.commit()
    db.refresh(project)
    return project


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, role = require_project(db, project_id, user, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only the project owner can delete it")
    db.delete(project)
    db.commit()
    return Response(status_code=204)


@app.post("/api/projects/{project_id}/requirements/extract")
def extract(project_id: int, payload: ExtractionRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project(db, project_id, user)
    return {"extracted": extract_requirements(payload.text), "processing": "local heuristic; review and save candidates"}


@app.get("/api/projects/{project_id}/requirements", response_model=list[RequirementRead])
def list_requirements(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project(db, project_id, user)
    return db.scalars(select(Requirement).where(Requirement.project_id == project_id)).all()


@app.put("/api/projects/{project_id}/requirements", response_model=list[RequirementRead])
def replace_requirements(project_id: int, items: list[RequirementInput], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _ = require_project(db, project_id, user, write=True)
    project.requirements.clear()
    db.flush()
    requirements = [Requirement(project_id=project_id, **item.model_dump()) for item in items]
    db.add_all(requirements)
    db.commit()
    return requirements


def _project_values(project: Project) -> list[dict]:
    return [{"key": item.key, "value": item.value} for item in project.requirements]


@app.post("/api/projects/{project_id}/simulate", response_model=SimulationResult)
def simulate_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _ = require_project(db, project_id, user)
    return SimulationResult(project_id=project_id, **simulate(_project_values(project)))


@app.get("/api/projects/{project_id}/scenarios", response_model=list[ScenarioRead])
def list_scenarios(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project(db, project_id, user)
    records = db.scalars(select(Scenario).where(Scenario.project_id == project_id).order_by(Scenario.id)).all()
    return [ScenarioRead(id=item.id, project_id=item.project_id, name=item.name, description=item.description, overrides=__import__("json").loads(item.overrides or "{}")) for item in records]


@app.post("/api/projects/{project_id}/scenarios", response_model=ScenarioRead, status_code=201)
def create_scenario(project_id: int, payload: ScenarioCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _ = require_project(db, project_id, user, write=True)
    allowed = {"users", "daily_events", "retention_days", "peak_factor", "budget", "avg_event_size_kb", "compute_instances", "compute_unit_cost", "database_monthly_cost", "cache_monthly_cost", "queue_monthly_cost", "storage_cost_per_gb", "network_monthly_cost"}
    unknown = set(payload.overrides) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported override keys: {', '.join(sorted(unknown))}")
    scenario = Scenario(project_id=project.id, name=payload.name.strip(), description=payload.description, overrides=__import__("json").dumps(payload.overrides))
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return ScenarioRead(id=scenario.id, project_id=project.id, name=scenario.name, description=scenario.description, overrides=payload.overrides)


@app.post("/api/projects/{project_id}/scenarios/{scenario_id}/simulate", response_model=SimulationResult)
def simulate_scenario(project_id: int, scenario_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _ = require_project(db, project_id, user)
    scenario = db.scalar(select(Scenario).where(Scenario.id == scenario_id, Scenario.project_id == project_id))
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    result = simulate(_project_values(project), __import__("json").loads(scenario.overrides or "{}"))
    return SimulationResult(project_id=project_id, scenario_id=scenario_id, **result)


@app.get("/api/projects/{project_id}/members", response_model=list[ProjectMemberRead])
def list_members(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _ = require_project(db, project_id, user)
    rows = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project.id)).all()
    result = [ProjectMemberRead(user_id=project.user_id, username=project.owner.username, role="owner")]
    result.extend(ProjectMemberRead(user_id=row.user_id, username=row.user.username, role=row.role) for row in rows)
    return result


@app.post("/api/projects/{project_id}/members", response_model=ProjectMemberRead, status_code=201)
def share_project(project_id: int, payload: ProjectShareCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, role = require_project(db, project_id, user, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can manage sharing")
    invitee = db.scalar(select(User).where(User.username == payload.username.lower()))
    if invitee is None:
        raise HTTPException(status_code=404, detail="No account exists with that username")
    if invitee.id == user.id:
        raise HTTPException(status_code=422, detail="You already own this project")
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == invitee.id))
    if member is None:
        member = ProjectMember(project_id=project_id, user_id=invitee.id, role=payload.role)
        db.add(member)
    else:
        member.role = payload.role
    db.commit()
    return ProjectMemberRead(user_id=invitee.id, username=invitee.username, role=payload.role)


@app.delete("/api/projects/{project_id}/members/{member_user_id}", status_code=204)
def remove_member(project_id: int, member_user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, role = require_project(db, project_id, user, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can manage sharing")
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == member_user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Project member not found")
    db.delete(member)
    db.commit()
    return Response(status_code=204)
