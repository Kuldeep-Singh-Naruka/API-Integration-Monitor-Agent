# API Integration Monitor

A production-ready backend service that actively monitors third-party API documentation for breaking and non-breaking changes.

Rather than a generic template, here is the **real status** of what this project actually does and how much is completed right now.

## 🚀 Current Status: Core Engine is Fully Built

The entire backend pipeline for monitoring, detecting, classifying, and storing API changes is **done and operational**.

### What is Completed:
- **FastAPI + PostgreSQL** backend with SQLAlchemy ORM.
- **Scraping Engine**: Uses [Tavily](https://tavily.com/) to fetch the latest documentation content, aggressively stripping out navigation boilerplate to reduce noise.
- **Change Detection**: Uses SHA-256 hashing to quickly detect if docs have changed, and [ChromaDB](https://www.trychroma.com/) for chunked vector storage.
- **AI Classification**: Uses [Groq](https://groq.com/) (LLM) to parse unified diffs and classify API changes strictly as `breaking` or `non-breaking`, providing developer-friendly summaries and fix suggestions.
- **Orchestration**: A bulletproof orchestration layer (`monitor_check.py`) that handles baseline establishments, unchanged states, and error handling. Faults are isolated so one failing API scrape doesn't crash the whole batch.
- **Automated Scheduling**: A protected `/internal/run-checks` endpoint triggered automatically by a **GitHub Actions daily cron job** (`.github/workflows/scheduled-check.yml`), secured by a timing-attack-safe shared secret.
- **RESTful Endpoints**: Full CRUD endpoints for managing Monitored APIs and reading Alerts.
---

## ⚙️ How it Works

1. **Trigger**: GitHub Actions runs daily at 03:17 UTC and hits `POST /internal/run-checks`.
2. **Fetch**: The system loops over all active APIs and fetches their docs via Tavily.
3. **Compare**: It strips boilerplate and hashes the markdown. If the hash matches the database, it skips to the next API to save resources.
4. **Diff & Analyze**: If the hash changes, it computes a pure python text diff of the markdown, then sends that diff to Groq.
5. **Classify**: Groq reads the diff, classifies the change, and generates an `Alert` (e.g., `"Endpoint /v1/charges deprecated"` -> `breaking`).
6. **Store**: The vector store (ChromaDB) is rebuilt with the new chunks, and the Postgres database is updated with the new hash, raw content, and the new Alert.

---

## 🛠 Setup & Local Development

### 1. Environment
Copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```
You will need:
- A local PostgreSQL database (`DATABASE_URL`)
- A [Tavily API Key](https://tavily.com/) (`TAVILY_API_KEY`)
- A [Groq API Key](https://console.groq.com/keys) (`GROQ_API_KEY`)
- A generated `SCHEDULER_SECRET` (Run: `python -c "import secrets; print(secrets.token_urlsafe(32))"`)

### 2. Install Dependencies
Make sure you are in your virtual environment, then run:
```bash
pip install -r requirements.txt
```

### 3. Run the Server
```bash
uvicorn main:app --reload
```
- **Docs (Swagger)**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### 4. Trigger a Manual Check
You can trigger the batch check locally (mimicking the GitHub Action) by passing your secret:
```bash
curl -X POST http://localhost:8000/internal/run-checks \
  -H "X-Scheduler-Secret: your_long_random_secret_here"
```
