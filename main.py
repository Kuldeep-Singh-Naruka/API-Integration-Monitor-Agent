import uvicorn
from fastapi import FastAPI

from app.core.config import settings
from app.database import Base, engine
from app.routers import apis, alerts


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------
app = FastAPI(
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
# Startup event — auto-create database tables
# ---------------------------------------------------------------------------
@app.on_event("startup")
def on_startup() -> None:
    """
    Create all database tables on application startup if they do not exist.
    In production you would use Alembic migrations instead, but this is
    convenient for development and first-time setup.
    """
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(apis.router)
app.include_router(alerts.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get(
    "/",
    tags=["Health"],
    summary="Health check",
)
def health_check() -> dict:
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
