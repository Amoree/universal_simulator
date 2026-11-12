from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Generator

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import Project, Requirement, Scenario, User
from app.schemas import AuthResponse, ProjectCreate, ProjectRead, RequirementRead, UserCreate, UserRead

app = FastAPI(title="Universal Simulator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    salt = os.getenv("PASSWORD_SALT", "universal-simulator-dev-salt").encode()
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    session_token = request.cookies.get("sessionid")
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user = db.scalar(select(User).where(User.session_token == session_token))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return user


def ensure_project_access(project: Project, user: User) -> Project:
    if project.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this project")
    return project


@app.on_event("startup")
def startup() -> None:
    from app.models import Base

    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=AuthResponse)
def register_user(payload: UserCreate, response: Response, db: Session = Depends(get_db)) -> dict:
    existing = db.scalar(select(User).where(User.username == payload.username))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    token = new_session_token()
    user = User(username=payload.username, password_hash=hash_password(payload.password), session_token=token)
    db.add(user)
    db.commit()
    db.refresh(user)

    response.set_cookie("sessionid", token, httponly=True, samesite="lax")
    return {"user": {"id": user.id, "username": user.username}}


@app.post("/api/auth/login", response_model=AuthResponse)
def login_user(payload: UserCreate, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or user.password_hash != hash_password(payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = new_session_token()
    user.session_token = token
    db.commit()
    response.set_cookie("sessionid", token, httponly=True, samesite="lax")
    return {"user": {"id": user.id, "username": user.username}}


@app.post("/api/auth/logout")
def logout_user(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    user.session_token = None
    db.commit()
    response.delete_cookie("sessionid")
    return {"status": "logged_out"}


@app.get("/api/auth/me", response_model=UserRead)
def get_me(user: User = Depends(get_current_user)) -> dict:
    return {"id": user.id, "username": user.username}


@app.get("/api/projects", response_model=list[ProjectRead])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Project]:
    projects = db.scalars(
        select(Project).where(Project.user_id == user.id).order_by(Project.id.desc())
    ).all()
    return projects


@app.post("/api/projects", response_model=ProjectRead)
def create_project(payload: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Project:
    project = Project(
        name=payload.name,
        description=payload.description,
        original_requirements=payload.original_requirements,
        user_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.get("/api/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ensure_project_access(project, user)


@app.put("/api/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project = ensure_project_access(project, user)
    project.name = payload.name
    project.description = payload.description
    project.original_requirements = payload.original_requirements
    db.commit()
    db.refresh(project)
    return project


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project = ensure_project_access(project, user)
    db.delete(project)
    db.commit()
    return {"status": "deleted"}


@app.post("/api/projects/{project_id}/requirements")
def create_requirement(
    project_id: int,
    payload: RequirementRead,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Requirement:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project_access(project, user)

    requirement = Requirement(
        category=payload.category,
        key=payload.key,
        value=payload.value,
        unit=payload.unit,
        source_text=payload.source_text,
        confidence=payload.confidence,
        confirmed=payload.confirmed,
        project_id=project.id,
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    return requirement


@app.get("/api/projects/{project_id}/requirements")
def get_requirements(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Requirement]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project_access(project, user)
    return db.scalars(select(Requirement).where(Requirement.project_id == project_id)).all()


@app.post("/api/projects/{project_id}/scenarios")
def create_scenario(
    project_id: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Scenario:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project_access(project, user)

    scenario = Scenario(
        name=payload.get("name", "Scenario"),
        description=payload.get("description"),
        overrides=str(payload.get("overrides", {})),
        project_id=project.id,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


@app.get("/api/projects/{project_id}/scenarios")
def get_scenarios(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Scenario]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project_access(project, user)
    return db.scalars(select(Scenario).where(Scenario.project_id == project_id)).all()
