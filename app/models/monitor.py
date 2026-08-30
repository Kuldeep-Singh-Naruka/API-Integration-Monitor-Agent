from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import String, Text, Boolean, Integer, ForeignKey, func
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
    alerts: Mapped[List["Alert"]] = relationship(
        "Alert",
        back_populates="api",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<MonitoredAPI id={self.id} name={self.name!r}>"


class Alert(Base):
    """
    Represents a detected change or breaking difference in a monitored API.

    Table: alerts
    """

    __tablename__ = "alerts"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign key — which API this alert belongs to
    api_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("monitored_apis.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Alert content
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Allowed values: 'breaking' or 'non-breaking'",
    )
    raw_diff: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # State
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        default=_utcnow,
        nullable=False,
    )

    # Relationship — back-reference to the parent MonitoredAPI
    api: Mapped["MonitoredAPI"] = relationship(
        "MonitoredAPI",
        back_populates="alerts",
    )

    def __repr__(self) -> str:
        return f"<Alert id={self.id} api_id={self.api_id} severity={self.severity!r}>"
