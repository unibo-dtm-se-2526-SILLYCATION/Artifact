"""Protected trip writes, intentionally not mounted by the public factory.

Tests mount this router under /api/v1 with verified-identity overrides.
Domain/application exceptions propagate until HTTP error integration is ready.
All business decisions, including approval rejection on overlap, remain in use
cases. Activation/completion use the server clock, never a client-supplied date.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, status

from sillycation.adapters.api.dependencies import (
    get_activate_trip,
    get_approve_join_request,
    get_archive_trip,
    get_authenticated_user_id,
    get_complete_trip,
    get_create_trip,
    get_current_date,
    get_new_invitation_code,
    get_new_join_request_id,
    get_new_trip_id,
    get_reject_join_request,
    get_request_join_trip,
)
from sillycation.adapters.api.mappers import join_request_response, trip_response
from sillycation.adapters.api.schemas.requests import (
    CreateTripRequest,
    RequestJoinTripRequest,
)
from sillycation.adapters.api.schemas.responses import JoinRequestResponse, TripResponse
from sillycation.application.trip_use_cases import (
    ActivateTrip,
    ApproveJoinRequest,
    ArchiveTrip,
    CompleteTrip,
    CreateTrip,
    RejectJoinRequest,
    RequestJoinTrip,
)
from sillycation.domain.identifiers import JoinRequestId, TripId, UserId
from sillycation.domain.value_objects import InvitationCode

router = APIRouter(tags=["trips"], dependencies=[Depends(get_authenticated_user_id)])
AuthenticatedUserId = Annotated[UserId, Depends(get_authenticated_user_id)]


@router.post("/trips", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
def create_trip(
    body: CreateTripRequest,
    actor: AuthenticatedUserId,
    use_case: Annotated[CreateTrip, Depends(get_create_trip)],
    trip_id: Annotated[TripId, Depends(get_new_trip_id)],
    invitation_code: Annotated[InvitationCode, Depends(get_new_invitation_code)],
) -> TripResponse:
    return trip_response(
        use_case.execute(
            trip_id=trip_id,
            name=body.name,
            creator_id=actor,
            start_date=body.start_date,
            end_date=body.end_date,
            invitation_code=invitation_code,
            description=body.description,
        )
    )


@router.post(
    "/join-requests",
    response_model=JoinRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def request_join_trip(
    body: RequestJoinTripRequest,
    actor: AuthenticatedUserId,
    use_case: Annotated[RequestJoinTrip, Depends(get_request_join_trip)],
    request_id: Annotated[JoinRequestId, Depends(get_new_join_request_id)],
) -> JoinRequestResponse:
    return join_request_response(
        use_case.execute(
            invitation_code=InvitationCode(body.invitation_code),
            request_id=request_id,
            user_id=actor,
        )
    )


@router.post(
    "/trips/{trip_id}/join-requests/{request_id}/approve",
    response_model=JoinRequestResponse,
)
def approve_join_request(
    trip_id: str,
    request_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[ApproveJoinRequest, Depends(get_approve_join_request)],
) -> JoinRequestResponse:
    return join_request_response(
        use_case.execute(
            trip_id=TripId(trip_id),
            request_id=JoinRequestId(request_id),
            requested_by=actor,
        )
    )


@router.post(
    "/trips/{trip_id}/join-requests/{request_id}/reject",
    response_model=JoinRequestResponse,
)
def reject_join_request(
    trip_id: str,
    request_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[RejectJoinRequest, Depends(get_reject_join_request)],
) -> JoinRequestResponse:
    return join_request_response(
        use_case.execute(
            trip_id=TripId(trip_id),
            request_id=JoinRequestId(request_id),
            requested_by=actor,
        )
    )


@router.post("/trips/{trip_id}/activate", response_model=TripResponse)
def activate_trip(
    trip_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[ActivateTrip, Depends(get_activate_trip)],
    current_date: Annotated[date, Depends(get_current_date)],
) -> TripResponse:
    return trip_response(
        use_case.execute(
            trip_id=TripId(trip_id), requested_by=actor, current_date=current_date
        )
    )


@router.post("/trips/{trip_id}/complete", response_model=TripResponse)
def complete_trip(
    trip_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[CompleteTrip, Depends(get_complete_trip)],
    current_date: Annotated[date, Depends(get_current_date)],
) -> TripResponse:
    return trip_response(
        use_case.execute(
            trip_id=TripId(trip_id), requested_by=actor, current_date=current_date
        )
    )


@router.post("/trips/{trip_id}/archive", response_model=TripResponse)
def archive_trip(
    trip_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[ArchiveTrip, Depends(get_archive_trip)],
) -> TripResponse:
    return trip_response(use_case.execute(trip_id=TripId(trip_id), requested_by=actor))
