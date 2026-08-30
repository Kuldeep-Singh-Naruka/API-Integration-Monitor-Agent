from datetime import datetime, timezone
from typing import List

from sqlalchemy import String, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    """Return the current UTC time. Used as a default for datetime columns."""
    return datetime.now(timezone.utc)


class MonitoredAPI(Base):
    """
    Represents a third-party API that the system actively monitors.

    Table: monitored_apis
    """

    __tablename__ = "monitored_apis"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Core fields
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    docs_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    # Relationship — one MonitoredAPI has many Alerts
    # String reference "Alert" avoids circular imports between model files
    alerts: Mapped[List["Alert"]] = relationship(
        "Alert",
        back_populates="api",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<MonitoredAPI id={self.id} name={self.name!r}>"
