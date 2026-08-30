from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from typing import Generator

from app.core.config import settings


# ---------------------------------------------------------------------------
# Engine — one engine per application, reused for all connections
# ---------------------------------------------------------------------------
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Log SQL statements when DEBUG=True
)

# ---------------------------------------------------------------------------
# Session factory — each request gets its own session via get_db()
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Declarative base — all ORM models inherit from this
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Dependency — inject into FastAPI route handlers via Depends(get_db)
# ---------------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """
    Yield a database session for the duration of one request.
    Always closes the session in the finally block, even on errors.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
