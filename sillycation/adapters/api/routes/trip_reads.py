"""Trip reads whose permissions are enforced by the existing use cases."""

from typing import Annotated

from fastapi import APIRouter, Depends

from sillycation.adapters.api.dependencies import (
    get_authenticated_user_id,
    get_list_my_trips,
    get_participant_ranking,
    get_pending_join_requests,
    get_trip_dashboard,
    get_trip_episodes,
    get_trip_invitation_code,
    get_trip_participants,
)
from sillycation.adapters.api.mappers import (
    dashboard_response,
    episode_response,
    invitation_code_response,
    join_request_response,
    participant_response,
    ranking_entry_response,
    trip_summary_response,
)
from sillycation.adapters.api.openapi import BEARER_UNAUTHORIZED, error_responses
from sillycation.adapters.api.schemas.responses import (
    EpisodeResponse,
    InvitationCodeResponse,
    JoinRequestResponse,
    ParticipantResponse,
    RankingEntryResponse,
    TripDashboardResponse,
    TripSummaryResponse,
)
from sillycation.application.episode_read_use_cases import (
    GetTripDashboard,
    ListTripEpisodes,
)
from sillycation.application.ranking_use_cases import GetParticipantRanking
from sillycation.application.trip_read_use_cases import (
    GetPendingJoinRequests,
    GetTripInvitationCode,
    GetTripParticipants,
    ListMyTrips,
)
from sillycation.domain.identifiers import TripId, UserId

# Run the gate before constructing any use case/repository, even if a future
# handler inadvertently omits the identity argument. FastAPI caches it per request.
router = APIRouter()
trip_list_router = APIRouter(
    prefix="/trips",
    tags=["trips"],
    dependencies=[Depends(get_authenticated_user_id)],
)
_details_router = APIRouter(
    prefix="/trips",
    tags=["trips"],
    dependencies=[Depends(get_authenticated_user_id)],
)
AuthenticatedUserId = Annotated[UserId, Depends(get_authenticated_user_id)]


@trip_list_router.get(
    "",
    response_model=list[TripSummaryResponse],
    responses={**error_responses(), 401: BEARER_UNAUTHORIZED},
)
def list_my_trips(
    actor: AuthenticatedUserId,
    use_case: Annotated[ListMyTrips, Depends(get_list_my_trips)],
    archived: bool = False,
) -> list[TripSummaryResponse]:
    return [
        trip_summary_response(trip)
        for trip in use_case.execute(requested_by=actor, archived=archived)
    ]


@_details_router.get(
    "/{trip_id}/invitation-code",
    response_model=InvitationCodeResponse,
    responses=error_responses("not_authorized", "not_found"),
)
def read_invitation_code(
    trip_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[GetTripInvitationCode, Depends(get_trip_invitation_code)],
) -> InvitationCodeResponse:
    return invitation_code_response(
        use_case.execute(trip_id=TripId(trip_id), requested_by=actor)
    )


@_details_router.get(
    "/{trip_id}/join-requests",
    response_model=list[JoinRequestResponse],
    responses=error_responses("not_authorized", "not_found"),
)
def read_pending_join_requests(
    trip_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[GetPendingJoinRequests, Depends(get_pending_join_requests)],
) -> list[JoinRequestResponse]:
    return [
        join_request_response(request)
        for request in use_case.execute(trip_id=TripId(trip_id), requested_by=actor)
    ]


@_details_router.get(
    "/{trip_id}/participants",
    response_model=list[ParticipantResponse],
    responses=error_responses("not_authorized", "not_found"),
)
def read_participants(
    trip_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[GetTripParticipants, Depends(get_trip_participants)],
) -> list[ParticipantResponse]:
    return [
        participant_response(participant)
        for participant in use_case.execute(trip_id=TripId(trip_id), requested_by=actor)
    ]


@_details_router.get(
    "/{trip_id}/episodes",
    response_model=list[EpisodeResponse],
    responses=error_responses("not_authorized", "not_found"),
)
def read_episodes(
    trip_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[ListTripEpisodes, Depends(get_trip_episodes)],
) -> list[EpisodeResponse]:
    return [
        episode_response(episode)
        for episode in use_case.execute(trip_id=TripId(trip_id), requested_by=actor)
    ]


@_details_router.get(
    "/{trip_id}/ranking",
    response_model=list[RankingEntryResponse],
    responses=error_responses("not_authorized", "not_found", "invalid_data"),
)
def read_ranking(
    trip_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[GetParticipantRanking, Depends(get_participant_ranking)],
) -> list[RankingEntryResponse]:
    return [
        ranking_entry_response(entry)
        for entry in use_case.execute(trip_id=TripId(trip_id), requested_by=actor)
    ]


@_details_router.get(
    "/{trip_id}/dashboard",
    response_model=TripDashboardResponse,
    responses=error_responses("not_authorized", "not_found", "invalid_data"),
)
def read_dashboard(
    trip_id: str,
    actor: AuthenticatedUserId,
    use_case: Annotated[GetTripDashboard, Depends(get_trip_dashboard)],
) -> TripDashboardResponse:
    return dashboard_response(
        use_case.execute(trip_id=TripId(trip_id), requested_by=actor)
    )


router.include_router(trip_list_router)
router.include_router(_details_router)
