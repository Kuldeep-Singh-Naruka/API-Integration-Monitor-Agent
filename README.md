# API Integration Monitor

A production-ready **FastAPI + PostgreSQL** service that tracks third-party API documentation for breaking and non-breaking changes.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Framework | FastAPI |
| Database | PostgreSQL |
| ORM | SQLAlchemy 2.0 |
| DB Driver | psycopg2-binary |
| Settings | pydantic-settings |
| Migrations | Alembic |
| Server | Uvicorn |

---

## Project Structure

```
api-monitor/
├── app/
│   ├── __init__.py
│   ├── database.py           # Engine, session, Base, get_db()
│   ├── models/
│   │   ├── __init__.py
│   │   └── monitor.py        # MonitoredAPI & Alert ORM models
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── api_schema.py     # Pydantic schemas for APIs
│   │   └── alert_schema.py   # Pydantic schemas for Alerts
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── apis.py           # /apis endpoints
│   │   └── alerts.py         # /alerts endpoints
│   └── core/
│       ├── __init__.py
│       └── config.py         # Settings via pydantic-settings
├── main.py                   # FastAPI app entry point
├── .env                      # Local secrets — NOT committed to Git
├── .env.example              # Key template — committed to Git
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Set up your environment

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@localhost:5432/api_integration_monitor
APP_NAME=API Integration Monitor
DEBUG=True
```

### 2. Create the PostgreSQL database

```sql
CREATE DATABASE api_integration_monitor;
CREATE USER USER WITH PASSWORD 'PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE api_integration_monitor TO USER;
```

### 3. Install dependencies (inside your virtualenv)

```bash
pip install -r requirements.txt
```

### 4. Run the server

```bash
# Option A — direct
python main.py

# Option B — uvicorn with hot reload
uvicorn main:app --reload
```

Tables are created automatically on startup via `Base.metadata.create_all()`.

### 5. Open the interactive API docs

- **Swagger UI** → [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc** → [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## API Endpoints

### Health

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `GET` | `/` | 200 | Health check |

### Monitored APIs

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/apis/` | 201 | Register a new API to monitor |
| `GET` | `/apis/` | 200 | List all monitored APIs |
| `GET` | `/apis/{api_id}` | 200 / 404 | Get a single API |
| `PATCH` | `/apis/{api_id}` | 200 / 404 | Toggle `is_active` |
| `DELETE` | `/apis/{api_id}` | 204 / 404 | Delete an API and its alerts |

### Alerts

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/alerts/` | 201 | Create a new alert |
| `GET` | `/alerts/` | 200 | List all alerts |
| `GET` | `/alerts/api/{api_id}` | 200 | All alerts for one API |
| `GET` | `/alerts/{alert_id}` | 200 / 404 | Get a single alert |
| `PATCH` | `/alerts/{alert_id}` | 200 / 404 | Mark as read |

---

## Database Schema

### `monitored_apis`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key, auto-increment |
| `name` | `VARCHAR(255)` | Not nullable |
| `docs_url` | `VARCHAR(500)` | Not nullable |
| `is_active` | `BOOLEAN` | Default `true` |
| `created_at` | `TIMESTAMP` | Auto-set on insert (UTC) |
| `updated_at` | `TIMESTAMP` | Auto-set on insert + update (UTC) |

### `alerts`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INTEGER` | Primary key, auto-increment |
| `api_id` | `INTEGER` | FK → `monitored_apis.id` (cascade delete) |
| `summary` | `TEXT` | Not nullable |
| `severity` | `VARCHAR(50)` | `"breaking"` or `"non-breaking"` |
| `raw_diff` | `TEXT` | Nullable |
| `is_read` | `BOOLEAN` | Default `false` |
| `created_at` | `TIMESTAMP` | Auto-set on insert (UTC) |

---

## Example Requests

### Register an API

```bash
curl -X POST http://localhost:8000/apis/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Stripe API", "docs_url": "https://stripe.com/docs/api"}'
```

### Create an Alert

```bash
curl -X POST http://localhost:8000/alerts/ \
  -H "Content-Type: application/json" \
  -d '{
    "api_id": 1,
    "summary": "Endpoint /v1/charges deprecated",
    "severity": "breaking",
    "raw_diff": "- /v1/charges\n+ /v1/payment_intents"
  }'
```

### Mark Alert as Read

```bash
curl -X PATCH http://localhost:8000/alerts/1 \
  -H "Content-Type: application/json" \
  -d '{"is_read": true}'
```

---

## Week 2 Roadmap

- [ ] Alembic migration setup (`alembic init`)
- [ ] Background scheduler to fetch and diff API docs
- [ ] AI-powered change detection (Gemini API)
- [ ] Email / webhook notifications for breaking changes
- [ ] Pytest test suite with a test database

---

## Security Notes

- `.env` is in `.gitignore` — **never commit it**
- All secrets are loaded via `pydantic-settings` — **nothing hardcoded**
- Use `GRANT` / `REVOKE` in PostgreSQL to limit user permissions in production
