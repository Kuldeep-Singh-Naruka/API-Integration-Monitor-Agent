from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.monitor import Alert, MonitoredAPI
from app.schemas.alert_schema import (
    AlertCreate,
    AlertUpdate,
    AlertResponse,
)

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
)


# ---------------------------------------------------------------------------
# POST /alerts — Create a new alert
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=AlertResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new alert for a monitored API",
)
def create_alert(
    payload: AlertCreate,
    db: Session = Depends(get_db),
) -> AlertResponse:
    """
    Create a new alert linked to a monitored API.
    Returns 404 if the referenced api_id does not exist.
    Week 2 diff logic will call this internally to record detected changes.
    """
    # Validate that the referenced API actually exists
    api = db.query(MonitoredAPI).filter(MonitoredAPI.id == payload.api_id).first()
    if api is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitored API with id={payload.api_id} not found.",
        )

    new_alert = Alert(
        api_id=payload.api_id,
        summary=payload.summary,
        severity=payload.severity,
        raw_diff=payload.raw_diff,
    )
    db.add(new_alert)
    db.commit()
    db.refresh(new_alert)
    return new_alert  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /alerts — List all alerts
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=List[AlertResponse],
    status_code=status.HTTP_200_OK,
    summary="List all alerts",
)
def get_all_alerts(
    db: Session = Depends(get_db),
) -> List[AlertResponse]:
    """
    Return every alert in the system across all monitored APIs.
    """
    alerts = db.query(Alert).all()
    return alerts  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /alerts/api/{api_id} — All alerts for a specific API
# IMPORTANT: This route MUST be defined before GET /alerts/{alert_id}
# so FastAPI does not try to parse the literal string "api" as an integer.
# ---------------------------------------------------------------------------
@router.get(
    "/api/{api_id}",
    response_model=List[AlertResponse],
    status_code=status.HTTP_200_OK,
    summary="Get all alerts for a specific monitored API",
)
def get_alerts_by_api(
    api_id: int,
    db: Session = Depends(get_db),
) -> List[AlertResponse]:
    """
    Return all alerts that belong to the monitored API with the given api_id.
    Returns an empty list if the API exists but has no alerts.
    """
    alerts = db.query(Alert).filter(Alert.api_id == api_id).all()
    return alerts  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /alerts/{alert_id} — Retrieve a single alert
# ---------------------------------------------------------------------------
@router.get(
    "/{alert_id}",
    response_model=AlertResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single alert by ID",
)
def get_alert(
    alert_id: int,
    db: Session = Depends(get_db),
) -> AlertResponse:
    """
    Return the alert with the given id.
    Raises 404 if no record is found.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with id={alert_id} not found.",
        )
    return alert  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# PATCH /alerts/{alert_id} — Mark an alert as read
# ---------------------------------------------------------------------------
@router.patch(
    "/{alert_id}",
    response_model=AlertResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an alert (e.g. mark as read)",
)
def update_alert(
    alert_id: int,
    payload: AlertUpdate,
    db: Session = Depends(get_db),
) -> AlertResponse:
    """
    Partially update an alert — currently supports toggling is_read.
    Raises 404 if no record is found.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with id={alert_id} not found.",
        )

    # Only update fields that were explicitly provided
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(alert, field, value)

    db.commit()
    db.refresh(alert)
    return alert  # type: ignore[return-value]
