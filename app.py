"""Turn plain-language product requirements into a reviewed build specification.

This service can use an OpenAI-compatible chat-completions endpoint to generate
scaffold files. Without model credentials it provides a transparent local
blueprint, and never pretends that estimates or a generic template are a built
product. Generated files are returned for review; they are never executed.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

app = FastAPI(
    title="Universal Simulator — Requirements to Solution",
    version="0.2.0",
    description="Convert product requirements into a traceable solution blueprint and optional code scaffold.",
)


class SolutionRequest(BaseModel):
    product_name: str = Field(min_length=2, max_length=120)
    requirements: str = Field(min_length=20, max_length=40_000)
    target_stack: str | None = Field(default=None, max_length=500)
    include_code: bool = True

    @field_validator("requirements")
    @classmethod
    def requirements_must_have_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Provide product requirements in natural language.")
        return value.strip()


class GeneratedFile(BaseModel):
    path: str = Field(min_length=1, max_length=180)
    content: str = Field(max_length=100_000)

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = value.replace("\\", "/")
        if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
            raise ValueError("Generated file paths must be relative.")
        if any(part in {"", ".", ".."} for part in path.split("/")):
            raise ValueError("Generated file path contains an unsafe component.")
        return path


class SolutionBundle(BaseModel):
    summary: str
    assumptions: list[str] = []
    open_questions: list[str] = []
    requirements: list[dict[str, Any]] = []
    user_stories: list[dict[str, Any]] = []
    architecture: dict[str, Any] = {}
    data_model: list[dict[str, Any]] = []
    api_contract: list[dict[str, Any]] = []
    security_and_quality: list[str] = []
    implementation_plan: list[dict[str, Any]] = []
    test_plan: list[dict[str, Any]] = []
    files: list[GeneratedFile] = []


# Small in-memory demo store. Use a database for multi-process or durable operation.
solutions: dict[str, dict[str, Any]] = {}

SYSTEM_PROMPT = """You are a senior product engineer converting product requirements into an implementable software solution.
Return one JSON object only, matching these keys:
summary (string), assumptions (string array), open_questions (string array),
requirements (array of {id, statement, acceptance_criteria: string array, priority}),
user_stories (array of {story, acceptance_criteria: string array, requirement_ids: string array}),
architecture (object with overview, components array, technology_choices array),
data_model (array of {name, purpose, fields: string array}),
api_contract (array of {method, path, purpose, request: string, response: string, requirement_ids: string array}),
security_and_quality (string array),
implementation_plan (array of {step, deliverable, requirement_ids: string array}),
test_plan (array of {scenario, expected_result, requirement_ids: string array}),
files (array of {path, content}).

Decompose the supplied requirements, including non-numeric functional, user, security, and operational requirements. Preserve traceability: assign stable IDs (FR-001 etc. for functional requirements, NFR-001 for nonfunctional) and reference them in stories, APIs, tests, and implementation steps. Identify ambiguity as open questions and mark assumptions explicitly; do not silently invent regulated/legal guarantees. Recommend a coherent, modest stack if none is given. Prioritize a small runnable MVP, include setup instructions and tests, and ensure the files form a coherent project that can be built. Do not claim code is tested or production-ready. Never include real secrets or real personal/health data. Generated files are untrusted source code: create only ordinary project files, never malware, credential theft, destructive scripts, or hidden execution hooks. Keep the output focused and limit files to 20, each under 100 KB. If include_code is false, return an empty files array."""


def local_blueprint(request: SolutionRequest) -> dict[str, Any]:
    """Useful, honest offline mode: structure requirements without claiming code generation."""
    lines = [line.strip(" \t-*•\r") for line in request.requirements.splitlines()]
    statements = [line for line in lines if len(line) >= 8]
    if not statements:
        statements = [request.requirements.strip()]
    requirements = [
        {
            "id": f"REQ-{index:03d}",
            "statement": statement,
            "acceptance_criteria": [],
            "priority": "needs_review",
        }
        for index, statement in enumerate(statements[:100], 1)
    ]
    stack = request.target_stack or "Not specified; choose and validate a stack during solution design."
    return {
        "summary": f"Structured blueprint for {request.product_name}. Configure a model provider to generate a project scaffold.",
        "assumptions": ["Each non-empty input line is preserved as a candidate requirement; refine grouping and acceptance criteria with stakeholders."],
        "open_questions": ["Which users, deployment environment, integrations, and data sensitivity constraints apply?", "What measurable acceptance criteria define success for each requirement?"],
        "requirements": requirements,
        "user_stories": [],
        "architecture": {
            "overview": "Architecture requires domain-specific design. The offline mode does not invent a software design from incomplete information.",
            "components": [],
            "technology_choices": [stack],
        },
        "data_model": [],
        "api_contract": [],
        "security_and_quality": ["Review authentication, authorization, privacy, encryption, retention, accessibility, and operational requirements before implementation."],
        "implementation_plan": [{"step": "Refine requirements", "deliverable": "Prioritized, testable acceptance criteria and resolved open questions", "requirement_ids": [item["id"] for item in requirements]}],
        "test_plan": [],
        "files": [],
    }


def model_blueprint(request: SolutionRequest) -> dict[str, Any]:
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    if not api_key or not model:
        raise HTTPException(status_code=503, detail="Code generation is not configured. Set LLM_API_KEY and LLM_MODEL; local blueprint mode remains available with include_code=false.")

    user_payload = {
        "product_name": request.product_name,
        "requirements": request.requirements,
        "target_stack": request.target_stack or "Recommend a modest, maintainable stack.",
        "include_code": request.include_code,
    }
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        generated = json.loads(content)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="The configured model service could not be reached.") from exc
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="The model did not return a valid solution JSON bundle.") from exc

    try:
        bundle = SolutionBundle.model_validate(generated)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"The generated solution did not match the required schema: {exc}") from exc
    if len(bundle.files) > 20:
        raise HTTPException(status_code=502, detail="The generated bundle exceeded the 20-file limit.")
    return bundle.model_dump()


@app.get("/health")
def health() -> dict[str, str]:
    configured = bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL"))
    return {"status": "ok", "code_generation": "configured" if configured else "not configured; blueprint mode available"}


@app.post("/api/solutions", status_code=201)
def create_solution(request: SolutionRequest) -> dict[str, Any]:
    if request.include_code:
        bundle = model_blueprint(request)
        mode = "model_generated"
    else:
        bundle = local_blueprint(request)
        mode = "local_blueprint"
    solution_id = "sol_" + secrets.token_urlsafe(12)
    result = {
        "solution_id": solution_id,
        "product_name": request.product_name,
        "mode": mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "review_required": True,
        "build_instructions": "Generated artifacts are untrusted drafts. Review them, install dependencies, and run tests in an isolated development environment before use.",
        **bundle,
    }
    solutions[solution_id] = result
    return result


@app.get("/api/solutions/{solution_id}")
def get_solution(solution_id: str) -> dict[str, Any]:
    result = solutions.get(solution_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Solution not found in this process.")
    return result


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Turn product requirements into a traceable software solution.", "docs": "/docs", "create_solution": "POST /api/solutions"}
