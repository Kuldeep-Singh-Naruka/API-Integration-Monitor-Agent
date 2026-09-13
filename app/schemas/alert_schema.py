from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

# The three allowed severity values, kept as a single type alias so that
# both AlertCreate and create_alert_record() share an identical annotation.
SeverityLiteral = Literal["breaking", "non-breaking", "error"]


class AlertCreate(BaseModel):
    """
    Schema for creating a new alert.
    raw_diff is optional — may not be available for all alert types.
    """

    api_id: int
    summary: str
    severity: SeverityLiteral
    # "breaking"     — a detected doc-content change that breaks backwards compat
    # "non-breaking" — a detected doc-content change that is backwards-compatible
    # "error"        — the scraper failed to fetch the docs at all (no content
    #                  diff available; raw_diff will be None)
    raw_diff: Optional[str] = None
    # suggested_fix is normally populated by the LLM summariser, but a caller
    # may supply one manually when constructing an alert without going through
    # the summariser (e.g. in tests or manual interventions).
    suggested_fix: Optional[str] = None


class AlertUpdate(BaseModel):
    """
    Schema for partially updating an alert.
    Currently only supports marking as read/unread.
    """

    is_read: Optional[bool] = None


class AlertResponse(BaseModel):
    """
    Schema for returning an alert record in API responses.
    Maps directly from the ORM model via from_attributes=True.
    """

    id: int
    api_id: int
    summary: str
    severity: str
    raw_diff: Optional[str]
    suggested_fix: Optional[str]
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
