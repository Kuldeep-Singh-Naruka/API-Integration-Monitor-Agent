from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AlertCreate(BaseModel):
    """
    Schema for creating a new alert.
    raw_diff is optional — may not be available for all alert types.
    """

    api_id: int
    summary: str
    severity: str  # Expected values: "breaking" or "non-breaking"
    raw_diff: Optional[str] = None


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
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
