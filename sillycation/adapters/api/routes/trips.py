"""Authenticated trip writes through the transactional application facade."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, status

from sillycation.adapters.api.dependencies import (
    get_authenticated_user_id,
    get_current_date,
    get_new_invitation_code,
    get_new_join_request_id,
    get_new_trip_id,
    get_transactional_commands,
)
from sillycation.adapters.api.mappers import join_request_response, trip_response
from sillycation.adapters.api.openapi import BEARER_UNAUTHORIZED, error_responses
from sillycation.adapters.api.schemas.requests import (
    CreateTripRequest,
    RequestJoinTripRequest,
)
from sillycation.adapters.api.schemas.responses import JoinRequestResponse, TripResponse
from sillycation.application.transactional import TransactionalCommands
from sillycation.domain.identifiers import JoinRequestId, TripId, UserId
from sillycation.domain.value_objects import InvitationCode

router = APIRouter(
    tags=["trips"],
    dependencies=[Depends(get_authenticated_user_id)],
    responses={401: BEARER_UNAUTHORIZED},
)
AuthenticatedUserId = Annotated[UserId, Depends(get_authenticated_user_id)]
TripCommands = Annotated[TransactionalCommands, Depends(get_transactional_commands)]


@router.post(
    "/trips",
    response_model=TripResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(
        "not_found", "invalid_state", "duplicate", "invalid_data"
    ),
)
def create_trip(
    body: CreateTripRequest,
    actor: AuthenticatedUserId,
    commands: TripCommands,
    trip_id: Annotated[TripId, Depends(get_new_trip_id)],
    invitation_code: Annotated[InvitationCode, Depends(get_new_invitation_code)],
) -> TripResponse:
    return trip_response(
        commands.create_trip(
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
    responses=error_responses("not_found", "invalid_state", "duplicate"),
)
def request_join_trip(
    body: RequestJoinTripRequest,
    actor: AuthenticatedUserId,
    commands: TripCommands,
    request_id: Annotated[JoinRequestId, Depends(get_new_join_request_id)],
) -> JoinRequestResponse:
    return join_request_response(
        commands.request_join_trip(
            invitation_code=InvitationCode(body.invitation_code),
            request_id=request_id,
            user_id=actor,
        )
    )


@router.post(
    "/trips/{trip_id}/join-requests/{request_id}/approve",
    response_model=JoinRequestResponse,
    responses=error_responses("not_authorized", "not_found", "invalid_state"),
)
def approve_join_request(
    trip_id: str,
    request_id: str,
    actor: AuthenticatedUserId,
    commands: TripCommands,
) -> JoinRequestResponse:
    return join_request_response(
        commands.approve_join_request(
            trip_id=TripId(trip_id),
            request_id=JoinRequestId(request_id),
            requested_by=actor,
        )
    )


@router.post(
    "/trips/{trip_id}/join-requests/{request_id}/reject",
    response_model=JoinRequestResponse,
    responses=error_responses("not_authorized", "not_found", "invalid_state"),
)
def reject_join_request(
    trip_id: str,
    request_id: str,
    actor: AuthenticatedUserId,
    commands: TripCommands,
) -> JoinRequestResponse:
    return join_request_response(
        commands.reject_join_request(
            trip_id=TripId(trip_id),
            request_id=JoinRequestId(request_id),
            requested_by=actor,
        )
    )


@router.post(
    "/trips/{trip_id}/activate",
    response_model=TripResponse,
    responses=error_responses("not_authorized", "not_found", "invalid_state"),
)
def activate_trip(
    trip_id: str,
    actor: AuthenticatedUserId,
    commands: TripCommands,
    current_date: Annotated[date, Depends(get_current_date)],
) -> TripResponse:
    return trip_response(
        commands.activate_trip(
            trip_id=TripId(trip_id), requested_by=actor, current_date=current_date
        )
    )


@router.post(
    "/trips/{trip_id}/complete",
    response_model=TripResponse,
    responses=error_responses("not_authorized", "not_found", "invalid_state"),
)
def complete_trip(
    trip_id: str,
    actor: AuthenticatedUserId,
    commands: TripCommands,
    current_date: Annotated[date, Depends(get_current_date)],
) -> TripResponse:
    return trip_response(
        commands.complete_trip(
            trip_id=TripId(trip_id), requested_by=actor, current_date=current_date
        )
    )


@router.post(
    "/trips/{trip_id}/archive",
    response_model=TripResponse,
    responses=error_responses("not_authorized", "not_found", "invalid_state"),
)
def archive_trip(
    trip_id: str,
    actor: AuthenticatedUserId,
    commands: TripCommands,
) -> TripResponse:
    return trip_response(
        commands.archive_trip(trip_id=TripId(trip_id), requested_by=actor)
    )
