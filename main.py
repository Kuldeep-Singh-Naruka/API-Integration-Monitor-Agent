import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.core.config import settings
from app.database import Base, engine
from app.routers import monitored_apis, alerts, internal


# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated @app.on_event("startup")
# Runs setup code before the app starts accepting requests.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Create all database tables on startup if they do not exist.
    In production, use Alembic migrations instead of create_all().
    """
    Base.metadata.create_all(bind=engine)
    yield  # App runs here — add shutdown logic after yield if needed


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    description=(
        "Monitor third-party API documentation for breaking and non-breaking changes. "
        "Week 1 foundation — API registration and alert management."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(monitored_apis.router)
app.include_router(alerts.router)
# NOTE: This router is intended for the scheduled GitHub Actions workflow only.
# It is NOT a user-facing feature and should not be referenced in public docs.
app.include_router(internal.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get(
    "/",
    tags=["Health"],
    summary="Health check",
)
def health_check() -> dict[str, str]:
    """
    Confirm the application is running and return the configured app name.
    """
    return {"status": "ok", "app": settings.APP_NAME}


# ---------------------------------------------------------------------------
# Entry point — run with: python main.py
# Or run with: uvicorn main:app --reload
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
