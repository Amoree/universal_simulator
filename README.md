# Universal Simulator — Requirements to Buildable Solution

Universal Simulator turns natural-language product requirements into a structured, traceable solution design and (when configured with a model provider) a draft project scaffold. It is not a traffic, storage, or cost estimator. It does not claim that generated code is tested or production-ready.

## What it does

- Accepts complete product requirements as prose, bullets, user stories, and acceptance criteria—not just numeric inputs.
- Produces a solution bundle with decomposed requirements, assumptions, open questions, user stories, architecture, data model, API contract, security/quality considerations, implementation steps, and test scenarios.
- Can produce a set of project files using an OpenAI-compatible chat-completions API.
- Keeps generated files in the response for review; the service does not execute them or write to a repository.
- Provides an offline blueprint mode (`include_code: false`) when no model credentials are configured. Offline mode organizes input lines but deliberately does not pretend to design or build a complete system.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000/docs` to explore the API.

### Enable code generation

Configure a compatible provider in your environment (never commit credentials):

```bash
export LLM_API_KEY='your-provider-api-key'
export LLM_MODEL='your-model-name'
# Optional; defaults to https://api.openai.com/v1
export LLM_BASE_URL='https://api.openai.com/v1'
uvicorn app:app --reload
```

The configured model service receives the product name, requirements, and target stack. Review its privacy and data handling terms before sending sensitive requirements. Do not submit secrets or real personal, health, or regulated data.

## Create a solution

```bash
curl -X POST http://127.0.0.1:8000/api/solutions \
  -H 'Content-Type: application/json' \
  -d '{
    "product_name": "Community Clinic Booking",
    "target_stack": "Python 3.11, FastAPI, PostgreSQL, React",
    "include_code": true,
    "requirements": "Patients can create an account and book an appointment.\nClinic staff can publish available appointment slots.\nPatients can cancel up to 24 hours before the visit.\nStaff must only access records for their clinic.\nSend a confirmation after a booking is created."
  }'
```

The response contains a `solution_id`, traceable requirements and design artifacts, plus `files` when code generation is enabled. Retrieve the result again with `GET /api/solutions/{solution_id}` while the process remains running. The demonstration store is in-memory and is cleared on restart.

For the local, no-model blueprint, set `include_code` to `false`. To get actual implementation files, configure a model provider and set `include_code` to `true`; otherwise the API returns a clear configuration error rather than suggesting a blueprint is a built solution.

## Build and safety boundaries

Generated source is untrusted draft code. Inspect every file, run dependency/security checks, and test in an isolated environment before integrating it. The API validates the response shape and relative file paths, limits output to 20 files, and never executes generated content. It is a prototype: add authentication, durable storage, rate limits, job processing, stronger schema validation, tests, and deployment controls before exposing it to users. No generated output should be represented as production-ready without engineering review.
