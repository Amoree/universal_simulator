# Software Requirements Simulator

A lightweight MVP for turning plain-language software requirements into structured inputs and comparing planning scenarios.

## Features

- Create software projects
- Extract candidate requirements from plain text
- Review and edit requirement values
- Run a baseline simulation
- Create scenario overrides and compare against the baseline
- Transparent assumptions and warnings

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Then open:
- http://127.0.0.1:8001/
- http://127.0.0.1:8001/docs

## Notes

This MVP is intentionally explicit and conservative. It calculates only when enough inputs are present and makes assumptions visible in the UI.
