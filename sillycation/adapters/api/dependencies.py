"""Dependency graph for the upcoming protected endpoints.

The composition root must override repository providers before wiring routes.
Tests use app.dependency_overrides with the same functions. Nothing opens a DB
at import or app creation time. Missing configuration fails explicitly; no
fake identities or implicit repository instances are provided.

Repository lifetime and write transactions await persistence integration.
Authenticated identity and credential providers belong to step 15.
"""

from datetime import date
from secrets import token_urlsafe
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, status

from sillycation.application.episode_read_use_cases import (
    GetTripDashboard,
    ListTripEpisodes,
)
from sillycation.application.episode_use_cases import (
    CreateEpisode,
    DeleteEpisode,
    EditEpisode,
    SubmitEpisode,
)
from sillycation.application.ports.passwords import PasswordHasher
from sillycation.application.ports.repositories import (
    EpisodeRepository,
    TripRepository,
    UserRepository,
)
from sillycation.application.ranking_use_cases import GetParticipantRanking
from sillycation.application.trip_read_use_cases import (
    GetPendingJoinRequests,
    GetTripInvitationCode,
    GetTripParticipants,
    ListMyTrips,
)
from sillycation.application.trip_use_cases import (
    ActivateTrip,
    ApproveJoinRequest,
    ArchiveTrip,
    CompleteTrip,
    CreateTrip,
    RejectJoinRequest,
    RequestJoinTrip,
)
from sillycation.application.user_use_cases import RegisterUser
from sillycation.application.voting_use_cases import CastVote
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.value_objects import InvitationCode


def get_authenticated_user_id() -> UserId:
    """Block protected routes until step 15 supplies a verified identity.

    No headers, query parameters or body fields are trusted as an identity.
    This is an integration boundary, not an authentication implementation.
    Only tests currently override it. Protected routers remain unmounted until
    authentication, persistence composition and HTTP errors are integrated.
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Protected API is not configured",
    )


def get_trip_repository() -> TripRepository:
    raise RuntimeError("TripRepository provider has not been configured")


def get_episode_repository() -> EpisodeRepository:
    raise RuntimeError("EpisodeRepository provider has not been configured")


def get_user_repository() -> UserRepository:
    raise RuntimeError("UserRepository provider has not been configured")


def get_password_hasher() -> PasswordHasher:
    """Require a real hasher from the composition root; no insecure fallback."""
    raise RuntimeError("PasswordHasher provider has not been configured")


def get_new_user_id() -> UserId:
    return UserId(uuid4().hex)


def get_new_trip_id() -> TripId:
    return TripId(uuid4().hex)


def get_new_join_request_id() -> JoinRequestId:
    return JoinRequestId(uuid4().hex)


def get_new_episode_id() -> EpisodeId:
    return EpisodeId(uuid4().hex)


def get_new_vote_id() -> VoteId:
    return VoteId(uuid4().hex)


def get_new_invitation_code() -> InvitationCode:
    """Allocate a random code; uniqueness is checked by CreateTrip/persistence."""
    return InvitationCode(token_urlsafe(12))


def get_current_date() -> date:
    """Server-local calendar date; injectable for tests and deployment policy."""
    return date.today()


TripRepositoryDependency = Annotated[TripRepository, Depends(get_trip_repository)]
EpisodeRepositoryDependency = Annotated[
    EpisodeRepository, Depends(get_episode_repository)
]
UserRepositoryDependency = Annotated[UserRepository, Depends(get_user_repository)]
PasswordHasherDependency = Annotated[PasswordHasher, Depends(get_password_hasher)]


def get_list_my_trips(trips: TripRepositoryDependency) -> ListMyTrips:
    return ListMyTrips(trips)


def get_trip_invitation_code(trips: TripRepositoryDependency) -> GetTripInvitationCode:
    return GetTripInvitationCode(trips)


def get_pending_join_requests(
    trips: TripRepositoryDependency,
) -> GetPendingJoinRequests:
    return GetPendingJoinRequests(trips)


def get_trip_participants(trips: TripRepositoryDependency) -> GetTripParticipants:
    return GetTripParticipants(trips)


def get_trip_episodes(
    trips: TripRepositoryDependency, episodes: EpisodeRepositoryDependency
) -> ListTripEpisodes:
    return ListTripEpisodes(trips, episodes)


def get_participant_ranking(
    trips: TripRepositoryDependency, episodes: EpisodeRepositoryDependency
) -> GetParticipantRanking:
    return GetParticipantRanking(trips, episodes)


def get_trip_dashboard(
    trips: TripRepositoryDependency, episodes: EpisodeRepositoryDependency
) -> GetTripDashboard:
    return GetTripDashboard(trips, episodes)


def get_create_trip(
    trips: TripRepositoryDependency, users: UserRepositoryDependency
) -> CreateTrip:
    return CreateTrip(trips, users)


def get_request_join_trip(trips: TripRepositoryDependency) -> RequestJoinTrip:
    return RequestJoinTrip(trips)


def get_approve_join_request(trips: TripRepositoryDependency) -> ApproveJoinRequest:
    return ApproveJoinRequest(trips)


def get_reject_join_request(trips: TripRepositoryDependency) -> RejectJoinRequest:
    return RejectJoinRequest(trips)


def get_activate_trip(trips: TripRepositoryDependency) -> ActivateTrip:
    return ActivateTrip(trips)


def get_complete_trip(
    trips: TripRepositoryDependency, episodes: EpisodeRepositoryDependency
) -> CompleteTrip:
    return CompleteTrip(trips, episodes)


def get_archive_trip(trips: TripRepositoryDependency) -> ArchiveTrip:
    return ArchiveTrip(trips)


def get_create_episode(
    trips: TripRepositoryDependency, episodes: EpisodeRepositoryDependency
) -> CreateEpisode:
    return CreateEpisode(trips, episodes)


def get_edit_episode(
    trips: TripRepositoryDependency, episodes: EpisodeRepositoryDependency
) -> EditEpisode:
    return EditEpisode(trips, episodes)


def get_delete_episode(
    trips: TripRepositoryDependency, episodes: EpisodeRepositoryDependency
) -> DeleteEpisode:
    return DeleteEpisode(trips, episodes)


def get_submit_episode(
    trips: TripRepositoryDependency, episodes: EpisodeRepositoryDependency
) -> SubmitEpisode:
    return SubmitEpisode(trips, episodes)


def get_cast_vote(
    trips: TripRepositoryDependency, episodes: EpisodeRepositoryDependency
) -> CastVote:
    return CastVote(trips, episodes)


def get_register_user(
    users: UserRepositoryDependency, passwords: PasswordHasherDependency
) -> RegisterUser:
    return RegisterUser(users, passwords)
