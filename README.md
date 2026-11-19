# Universal Simulator — Care Network MVP

A small, runnable API prototype for exploring the patient-consented provider network described in the MVP requirements. It demonstrates patient enrollment, approved-provider access, exact identifier lookup, progressive record aggregation, current and historical views, and access audit events.

> **Safety and compliance boundary:** This is a local, in-memory prototype for synthetic data and product discussions only. It is **not** a production healthcare system and is not HIPAA/HITECH compliant. Do not enter real patient information. It has no durable encrypted database, production identity proofing, MFA, patient portal, key management, backups, clinical terminology validation, or validated legal/privacy controls. A real deployment requires a healthcare security architecture, qualified privacy/legal review, threat modeling, and operational controls before handling PHI.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ADMIN_TOKEN='replace-with-a-long-random-admin-secret'
export APPROVED_PROVIDER_IDS='provider-a,provider-b'
export PROVIDER_TOKENS_JSON='{"provider-a":"replace-with-provider-a-secret","provider-b":"replace-with-provider-b-secret"}'
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API docs. Configure secrets outside source control; `.env.example` is documentation only and is not loaded automatically.

## Prototype workflow

1. A provider requests participation at `POST /providers/register`; the provider remains pending.
2. An administrator approves it at `POST /admin/providers/{provider_id}/approve` using `ADMIN_TOKEN`. In this prototype, provider credentials and the approved-provider allowlist are configured through environment variables and require a restart to change.
3. An approved provider enrolls a patient at `POST /patients/enroll`. Enrollment requires explicit consent. The API returns a random internal patient lookup key; it does not accept SSNs.
4. A treating provider searches using exact full name and date of birth at `POST /patients/search`, explicitly attesting to a treatment relationship and giving a reason. The response includes candidate patient keys, not a medical record.
5. The provider retrieves `/patients/{patient_key}/current` or `/historical`, or adds a visit at `/patients/{patient_key}/records`. Each patient-specific operation requires the same treatment attestation and reason. Record access requires active consent.
6. Consent revocation is represented by `POST /patients/{patient_key}/consent/revoke` with a patient-confirmation attestation. This is a demo placeholder—not patient identity verification.
7. `GET /admin/audit` returns the in-memory access log to an administrator.

This network is progressive: it only contains records submitted by participating providers. It does not fan out queries to all healthcare providers. Candidate duplicates are returned for review; the prototype deliberately does not automatically merge records based only on name and date of birth.

## MVP coverage and gaps

| Requirement | Prototype behavior | Production gap |
|---|---|---|
| Patient consent | Explicit consent required at enrollment; status/date retained; revoke route | Patient identity, consent evidence, notices, and revocation UX need a real patient-controlled flow |
| Provider participation | Registration is pending until admin approval; requests require configured provider credentials | Credential issuance, NPI/organization verification, MFA, staff roles, and lifecycle management |
| Patient lookup | Exact name + DOB search restricted to approved providers; treatment attestation and reason required | Identity resolution, false-match handling, patient-approved identifiers, and stronger authorization |
| Record aggregation | Visits and clinical categories from participating providers are appended to one patient profile | Durable encrypted storage, standardized formats, provenance, reconciliation, and safe duplicate resolution |
| Current/historical views | Current includes five-year activity and active diagnoses/medications; historical includes older or archived entries | Clinician validation of date rules, terminology, and presentation |
| Security/audit | Bearer-token demo auth; access attempts and actions are logged in process memory | MFA, OIDC, encryption at rest/in transit, tamper-resistant audit, monitoring, retention, and incident response |

## Next implementation milestones

1. Validate workflows and consent language with clinicians, patients, and privacy counsel.
2. Replace in-memory state with a properly designed encrypted database and migrations; add backups, access controls, retention, and secret/key management.
3. Integrate an identity provider for provider SSO/MFA and patient identity verification; implement least-privilege staff roles and verified treatment relationships.
4. Define interoperable record ingestion and provenance (for example, FHIR), patient matching/manual reconciliation, and correction workflows.
5. Add patient-facing consent review/revocation, robust tests, threat modeling, accessibility, deployment automation, and independent security/compliance review.

## API notes

All provider endpoints use `Authorization: Bearer <provider-secret>`. Administrator endpoints use `Authorization: Bearer <ADMIN_TOKEN>`. Patient-specific provider operations require `treating_patient: true` and a non-empty `reason`. These attestations are useful for exercising the workflow, but do not replace real authorization controls. Audit events intentionally avoid storing search names, dates of birth, record contents, or tokens.
