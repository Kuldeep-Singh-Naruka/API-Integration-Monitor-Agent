from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, HttpUrl


class MonitoredAPICreate(BaseModel):
    """
    Schema for creating a new monitored API.
    Only the fields the client must provide.
    """

    name: str
    docs_url: str


class MonitoredAPIUpdate(BaseModel):
    """
    Schema for partially updating a monitored API.
    All fields optional — only provided fields are updated.
    """

    is_active: Optional[bool] = None


class MonitoredAPIResponse(BaseModel):
    """
    Schema for returning a monitored API record in API responses.
    Maps directly from the ORM model via from_attributes=True.
    """

    id: int
    name: str
    docs_url: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
