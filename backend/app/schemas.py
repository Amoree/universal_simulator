from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RequirementInput(BaseModel):
    category: str = "system"
    key: str = Field(min_length=1, max_length=80)
    value: str | None = None
    unit: str | None = None
    source_text: str | None = None
    confidence: Literal["low", "medium", "high"] = "medium"
    confirmed: bool = False


class RequirementRead(RequirementInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    original_requirements: str | None = None


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    requirements: list[RequirementRead] = []


class ExtractionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    overrides: dict[str, float] = {}


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
    warnings: list[str]
    assumptions: list[str]
