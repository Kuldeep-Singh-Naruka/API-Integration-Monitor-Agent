from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.monitored_api import MonitoredAPI
from app.schemas.monitored_api_schema import (
    MonitoredAPICreate,
    MonitoredAPIUpdate,
    MonitoredAPIResponse,
)

router = APIRouter(
    prefix="/monitored-apis",
    tags=["Monitored APIs"],
)


# ---------------------------------------------------------------------------
# POST /monitored-apis — Add a new API to monitor
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=MonitoredAPIResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new API to monitor",
)
def create_api(
    payload: MonitoredAPICreate,
    db: Session = Depends(get_db),
) -> MonitoredAPIResponse:
    """
    Register a new third-party API for monitoring.
    Returns the newly created record with its generated id and timestamps.
    """
    new_api = MonitoredAPI(
        name=payload.name,
        docs_url=payload.docs_url,
    )
    db.add(new_api)
    db.commit()
    db.refresh(new_api)
    return new_api  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /monitored-apis — List all monitored APIs
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=List[MonitoredAPIResponse],
    status_code=status.HTTP_200_OK,
    summary="List all monitored APIs",
)
def get_all_apis(
    db: Session = Depends(get_db),
) -> List[MonitoredAPIResponse]:
    """
    Return every API currently registered in the system.
    """
    apis = db.query(MonitoredAPI).all()
    return apis  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /monitored-apis/{api_id} — Retrieve a single API
# ---------------------------------------------------------------------------
@router.get(
    "/{api_id}",
    response_model=MonitoredAPIResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single monitored API by ID",
)
def get_api(
    api_id: int,
    db: Session = Depends(get_db),
) -> MonitoredAPIResponse:
    """
    Return the monitored API with the given id.
    Raises 404 if no record is found.
    """
    api = db.query(MonitoredAPI).filter(MonitoredAPI.id == api_id).first()
    if api is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitored API with id={api_id} not found.",
        )
    return api  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# PATCH /monitored-apis/{api_id} — Update is_active flag
# ---------------------------------------------------------------------------
@router.patch(
    "/{api_id}",
    response_model=MonitoredAPIResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a monitored API (toggle active status)",
)
def update_api(
    api_id: int,
    payload: MonitoredAPIUpdate,
    db: Session = Depends(get_db),
) -> MonitoredAPIResponse:
    """
    Partially update a monitored API — currently supports toggling is_active.
    Raises 404 if no record is found.
    """
    api = db.query(MonitoredAPI).filter(MonitoredAPI.id == api_id).first()
    if api is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitored API with id={api_id} not found.",
        )

    # Only update fields that were explicitly provided
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(api, field, value)

    db.commit()
    db.refresh(api)
    return api  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# DELETE /monitored-apis/{api_id} — Remove an API from monitoring
# ---------------------------------------------------------------------------
@router.delete(
    "/{api_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a monitored API",
)
def delete_api(
    api_id: int,
    db: Session = Depends(get_db),
) -> None:
    """
    Permanently delete a monitored API and all its associated alerts (cascade).
    Raises 404 if no record is found.
    Returns 204 No Content on success — no body.
    """
    api = db.query(MonitoredAPI).filter(MonitoredAPI.id == api_id).first()
    if api is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitored API with id={api_id} not found.",
        )

    db.delete(api)
    db.commit()
