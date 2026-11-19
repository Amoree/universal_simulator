# Universal Simulator — Requirements to Buildable Solution

Universal Simulator is a web app for entering plain-language product requirements and receiving a software solution draft. The page submits requirements to the backend, which asks a configured language model to analyze them and return a traceable design plus project files. This is not a traffic, storage, or cost estimator.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`. Enter a product name, optionally name your preferred stack, paste requirements, and select **Design and build the solution**. The page renders the returned specification and previews downloadable files. The API docs remain at `http://127.0.0.1:8000/docs`.

## Configure solution/code generation

The backend needs an OpenAI-compatible chat-completions provider. Set credentials in the server environment; never commit them to the repository.

```bash
export LLM_API_KEY='your-provider-api-key'
export LLM_MODEL='your-model-name'
# Optional. Defaults to https://api.openai.com/v1
export LLM_BASE_URL='https://api.openai.com/v1'
uvicorn app:app --reload
```

The web page checks `/health` and indicates whether code generation is configured. Without credentials, the backend returns a clear setup error rather than pretending that a limited text parser generated a software solution.

## Solution output

`POST /api/solutions` accepts `product_name`, natural-language `requirements`, optional `target_stack`, and `include_code`. The generated response can include decomposed functional/nonfunctional requirements, acceptance criteria, user stories, architecture, data entities, API outline, implementation steps, quality/security considerations, test scenarios, and up to 20 project files (each max 100 KB). `GET /api/solutions/{solution_id}` retrieves a result while the server process remains running.

The generated files are untrusted drafts. The simulator returns them for review; it does not execute them, write directly into a repository, run their tests, or deploy the system. Assemble downloaded files into a project and inspect, install, and test in an isolated environment before use. Model output may be incomplete or incorrect. Review all requirements and generated code before treating it as a build plan.

Do not submit secrets or real personal, health, or regulated data. Requirements are transmitted to the configured model provider; assess that provider's data-handling terms before use. The solution store is in-memory and is cleared on restart. Add authentication, durable storage, rate limiting, background jobs, stronger validation, automated tests, and deployment controls before exposing this prototype to users.
