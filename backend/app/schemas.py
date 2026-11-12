from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=200)


class UserLogin(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class UserRead(BaseModel):
    id: int
    username: str


class AuthResponse(BaseModel):
    user: UserRead


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    original_requirements: str | None = Field(default=None, max_length=20000)


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    requirements: list[RequirementRead] = Field(default_factory=list)


class RequirementInput(BaseModel):
    category: str = "system"
    key: str = Field(min_length=1, max_length=80)
    value: str | None = None
    unit: str | None = None
    source_text: str | None = None
    confidence: Literal["low", "medium", "high"] = "high"
    confirmed: bool = True


class RequirementRead(RequirementInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int


class ExtractionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    overrides: dict[str, float] = Field(default_factory=dict)


class ScenarioRead(BaseModel):
    id: int
    project_id: int
    name: str
    description: str | None
    overrides: dict[str, float]


class SimulationResult(BaseModel):
    project_id: int
    scenario_id: int | None = None
    summary: str
    average_rps: float | None = None
    peak_rps: float | None = None
    storage_gb: float | None = None
    monthly_budget_usd: float | None = None
    estimated_monthly_cost_usd: float | None = None
    budget_remaining_usd: float | None = None
    cost_breakdown: dict[str, float] = Field(default_factory=dict)
    architecture: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ProjectShareCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    role: Literal["viewer", "editor"] = "viewer"


class ProjectMemberRead(BaseModel):
    user_id: int
    username: str
    role: Literal["owner", "viewer", "editor"]
