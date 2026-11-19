"""Synthetic-data-only API prototype for a patient-consented care network.

Do not use this in production or with real patient information. State is held in
memory and is lost on restart; see README.md for security and compliance gaps.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

app = FastAPI(
    title="Universal Simulator — Care Network MVP",
    version="0.1.0",
    description="Synthetic-data prototype only; not for PHI or production use.",
)


class RecordCategory(str, Enum):
    diagnosis = "diagnosis"
    medication = "medication"
    procedure = "procedure"
    visit = "visit"
    allergy = "allergy"
    lab_result = "lab_result"


class ProviderRegistration(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    contact_email: str = Field(min_length=3, max_length=254)


class EnrollmentRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    date_of_birth: date
    consent: bool


class TreatmentAttestation(BaseModel):
    treating_patient: bool
    reason: str = Field(min_length=3, max_length=500)


class PatientSearch(TreatmentAttestation):
    full_name: str = Field(min_length=2, max_length=200)
    date_of_birth: date


class RecordInput(TreatmentAttestation):
    category: RecordCategory
    occurred_at: datetime
    summary: str = Field(min_length=1, max_length=2000)
    active: bool = False
    archived: bool = False


class ConsentRevocation(TreatmentAttestation):
    patient_confirmed: bool


# Deliberately ephemeral stores. Production persistence/encryption is not implemented.
providers: dict[str, dict[str, Any]] = {}
patients: dict[str, dict[str, Any]] = {}
records: dict[str, list[dict[str, Any]]] = {}
audit_events: list[dict[str, Any]] = []


def approved_provider_ids() -> set[str]:
    return {item.strip() for item in os.getenv("APPROVED_PROVIDER_IDS", "").split(",") if item.strip()}


def configured_provider_tokens() -> dict[str, str]:
    raw = os.getenv("PROVIDER_TOKENS_JSON", "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PROVIDER_TOKENS_JSON must be a JSON object") from exc
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise RuntimeError("PROVIDER_TOKENS_JSON must map provider IDs to token strings")
    return value


def log_event(
    *, provider_id: str | None, action: str, outcome: str,
    patient_key: str | None = None, reason: str | None = None,
) -> None:
    # Never include names, dates of birth, record contents, or credentials in audit details.
    audit_events.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider_id": provider_id,
        "action": action,
        "outcome": outcome,
        "patient_key": patient_key,
        "reason": reason,
    })


def provider_auth(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Provider authentication required")
    supplied = authorization.removeprefix("Bearer ")
    for provider_id, expected in configured_provider_tokens().items():
        if hmac.compare_digest(supplied, expected):
            if provider_id not in approved_provider_ids():
                log_event(provider_id=provider_id, action="provider_auth", outcome="denied")
                raise HTTPException(status_code=403, detail="Provider is not approved")
            return provider_id
    log_event(provider_id=None, action="provider_auth", outcome="denied")
    raise HTTPException(status_code=401, detail="Invalid provider credentials")


def admin_auth(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = os.getenv("ADMIN_TOKEN", "")
    supplied = authorization.removeprefix("Bearer ") if authorization and authorization.startswith("Bearer ") else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Administrator authentication required")


def assert_treatment(attestation: TreatmentAttestation, provider_id: str, action: str, patient_key: str) -> None:
    if not attestation.treating_patient:
        log_event(provider_id=provider_id, action=action, outcome="denied", patient_key=patient_key, reason=attestation.reason)
        raise HTTPException(status_code=403, detail="A treating relationship must be attested")


def require_patient(patient_key: str, provider_id: str, action: str, reason: str) -> dict[str, Any]:
    patient = patients.get(patient_key)
    if patient is None:
        log_event(provider_id=provider_id, action=action, outcome="not_found", patient_key=patient_key, reason=reason)
        raise HTTPException(status_code=404, detail="Patient not found")
    if patient["consent_status"] != "active":
        log_event(provider_id=provider_id, action=action, outcome="denied_no_consent", patient_key=patient_key, reason=reason)
        raise HTTPException(status_code=403, detail="Patient consent is not active")
    return patient


def public_patient(patient_key: str, patient: dict[str, Any]) -> dict[str, Any]:
    return {
        "patient_key": patient_key,
        "consent_status": patient["consent_status"],
        "consent_date": patient["consent_date"],
        "record_count": len(records.get(patient_key, [])),
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "prototype — synthetic data only"}


@app.post("/providers/register", status_code=status.HTTP_201_CREATED)
def register_provider(request: ProviderRegistration) -> dict[str, str]:
    provider_id = "prov_" + secrets.token_urlsafe(12)
    providers[provider_id] = {
        "organization_name": request.organization_name,
        "contact_email": request.contact_email,
        "status": "pending",
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"provider_id": provider_id, "status": "pending", "message": "Registration submitted for administrator review."}


@app.post("/admin/providers/{provider_id}/approve", dependencies=[Depends(admin_auth)])
def approve_provider(provider_id: str) -> dict[str, str]:
    provider = providers.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider registration not found")
    provider["status"] = "approved"
    # Runtime approval still requires provider credentials and allowlist configuration in the environment.
    return {"provider_id": provider_id, "status": "approved", "note": "Provision credentials and add this ID to APPROVED_PROVIDER_IDS before provider access."}


@app.post("/patients/enroll", status_code=status.HTTP_201_CREATED)
def enroll_patient(request: EnrollmentRequest, provider_id: str = Depends(provider_auth)) -> dict[str, Any]:
    if not request.consent:
        raise HTTPException(status_code=400, detail="Explicit patient consent is required")
    patient_key = "pt_" + secrets.token_urlsafe(18)
    patients[patient_key] = {
        "full_name": request.full_name.strip(),
        "date_of_birth": request.date_of_birth,
        "consent_status": "active",
        "consent_date": datetime.now(timezone.utc).isoformat(),
        "enrolled_by": provider_id,
    }
    records[patient_key] = []
    log_event(provider_id=provider_id, action="patient_enrollment", outcome="success", patient_key=patient_key, reason="consented enrollment")
    return public_patient(patient_key, patients[patient_key])


@app.post("/patients/search")
def search_patient(request: PatientSearch, provider_id: str = Depends(provider_auth)) -> dict[str, Any]:
    if not request.treating_patient:
        log_event(provider_id=provider_id, action="patient_search", outcome="denied", reason=request.reason)
        raise HTTPException(status_code=403, detail="A treating relationship must be attested")
    matches = []
    for patient_key, patient in patients.items():
        if (patient["full_name"].casefold() == request.full_name.strip().casefold()
                and patient["date_of_birth"] == request.date_of_birth
                and patient["consent_status"] == "active"):
            matches.append({"patient_key": patient_key, "consent_status": patient["consent_status"]})
    log_event(
        provider_id=provider_id, action="patient_search",
        outcome="matches_found" if matches else "no_match",
        patient_key=matches[0]["patient_key"] if len(matches) == 1 else None,
        reason=request.reason,
    )
    # Do not expose records in search results. Multiple matches require careful identity review.
    return {"matches": matches, "identity_review_required": len(matches) != 1}


@app.post("/patients/{patient_key}/records", status_code=status.HTTP_201_CREATED)
def add_record(patient_key: str, request: RecordInput, provider_id: str = Depends(provider_auth)) -> dict[str, Any]:
    assert_treatment(request, provider_id, "record_write", patient_key)
    require_patient(patient_key, provider_id, "record_write", request.reason)
    occurred_at = request.occurred_at
    if occurred_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="occurred_at must include a timezone")
    item = {
        "record_id": "rec_" + secrets.token_urlsafe(12),
        "source_provider_id": provider_id,
        "category": request.category.value,
        "occurred_at": occurred_at.astimezone(timezone.utc).isoformat(),
        "summary": request.summary,
        "active": request.active,
        "archived": request.archived,
    }
    records[patient_key].append(item)
    log_event(provider_id=provider_id, action="record_write", outcome="success", patient_key=patient_key, reason=request.reason)
    return {"record_id": item["record_id"], "status": "stored"}


def patient_view(patient_key: str, provider_id: str, attestation: TreatmentAttestation, view: str) -> dict[str, Any]:
    assert_treatment(attestation, provider_id, f"{view}_view", patient_key)
    require_patient(patient_key, provider_id, f"{view}_view", attestation.reason)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=365 * 5)
    patient_records = records.get(patient_key, [])
    parsed = [(item, datetime.fromisoformat(item["occurred_at"])) for item in patient_records]
    if view == "current":
        selected = [item for item, dt in parsed if dt >= cutoff and not item["archived"]]
        active_items = [item for item in patient_records if item["active"] and item["category"] in {"medication", "diagnosis"}]
        active_ids = {item["record_id"] for item in active_items}
        result_records = selected + [item for item in active_items if item["record_id"] not in {r["record_id"] for r in selected}]
    else:
        result_records = [item for item, dt in parsed if dt < cutoff or item["archived"]]
    log_event(provider_id=provider_id, action=f"{view}_view", outcome="success", patient_key=patient_key, reason=attestation.reason)
    return {
        "patient_key": patient_key,
        "view": view,
        "as_of": now.isoformat(),
        "records": sorted(result_records, key=lambda item: item["occurred_at"], reverse=True),
    }


@app.get("/patients/{patient_key}/current")
def current_view(
    patient_key: str,
    treating_patient: bool = Query(...),
    reason: str = Query(min_length=3, max_length=500),
    provider_id: str = Depends(provider_auth),
) -> dict[str, Any]:
    return patient_view(patient_key, provider_id, TreatmentAttestation(treating_patient=treating_patient, reason=reason), "current")


@app.get("/patients/{patient_key}/historical")
def historical_view(
    patient_key: str,
    treating_patient: bool = Query(...),
    reason: str = Query(min_length=3, max_length=500),
    provider_id: str = Depends(provider_auth),
) -> dict[str, Any]:
    return patient_view(patient_key, provider_id, TreatmentAttestation(treating_patient=treating_patient, reason=reason), "historical")


@app.post("/patients/{patient_key}/consent/revoke")
def revoke_consent(patient_key: str, request: ConsentRevocation, provider_id: str = Depends(provider_auth)) -> dict[str, str]:
    assert_treatment(request, provider_id, "consent_revocation", patient_key)
    patient = patients.get(patient_key)
    if patient is None:
        log_event(provider_id=provider_id, action="consent_revocation", outcome="not_found", patient_key=patient_key, reason=request.reason)
        raise HTTPException(status_code=404, detail="Patient not found")
    if not request.patient_confirmed:
        log_event(provider_id=provider_id, action="consent_revocation", outcome="denied", patient_key=patient_key, reason=request.reason)
        raise HTTPException(status_code=403, detail="Patient confirmation is required")
    patient["consent_status"] = "revoked"
    patient["consent_revoked_at"] = datetime.now(timezone.utc).isoformat()
    log_event(provider_id=provider_id, action="consent_revocation", outcome="success", patient_key=patient_key, reason=request.reason)
    return {"patient_key": patient_key, "consent_status": "revoked"}


@app.get("/admin/audit", dependencies=[Depends(admin_auth)])
def get_audit(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return {"events": audit_events[-limit:], "total_events_in_memory": len(audit_events)}
