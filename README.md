# Universal Simulator

A browser-based MVP requirements data-entry and simulation app. The browser is the product UI; FastAPI handles authentication, project persistence, ownership, collaboration, and all calculations.

## Run locally

Requires Python 3.10+.

```bash
cd backend
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Open <http://127.0.0.1:8001/>. API docs are disabled in this MVP. Set `COOKIE_SECURE=true` when serving over HTTPS. Configure `DATABASE_URL` to select a persistent database; SQLite is the local default.

## Authentication and ownership

- Register with a username (letters, numbers, `_`, `-`, `.`) and a password of at least 10 characters.
- Passwords are stored as salted scrypt hashes.
- Session cookies are HttpOnly, SameSite=Strict, random, stored server-side as hashes, and expire after 14 days. Logout revokes the current browser session.
- Project reads/writes require login. Owners may invite existing users as viewers or editors; editors may update project inputs, while only owners can manage members or delete projects.
- Unowned legacy projects are intentionally not exposed. The startup migration adds nullable ownership to old SQLite project tables; assign an owner deliberately if migrating existing user data.
- For production, use HTTPS, set `COOKIE_SECURE=true`, configure a trusted proxy and persistent secret/database, and add rate limiting and account recovery before public launch.

## Run tests

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

The tests exercise registration, login/logout, project ownership isolation, viewer/editor access, sharing, and cross-origin write rejection using an isolated in-memory SQLite database.

## Estimate model

The server calculates average and peak request rates, retained storage, and a monthly cost breakdown from explicit user-provided prices. Missing inputs remain missing; the model does not invent provider prices. Estimates are planning aids, not capacity or uptime guarantees.
