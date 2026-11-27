"""HTTP dependencies backed by application ports configured in the lifespan."""

from dataclasses import dataclass
from datetime import date
import logging
from secrets import token_urlsafe
from typing import Annotated, Callable, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError

from sillycation.adapters.api.authentication import (
    HttpAuthentication,
    authentication_required,
)
from sillycation.application.episode_read_use_cases import (
    GetTripDashboard,
    ListTripEpisodes,
)
from sillycation.application.ports.passwords import PasswordHasher
from sillycation.application.ports.repositories import (
    EpisodeRepository,
    TripRepository,
    UserRepository,
)
from sillycation.application.ports.unit_of_work import UnitOfWork
from sillycation.application.ranking_use_cases import GetParticipantRanking
from sillycation.application.trip_read_use_cases import (
    GetPendingJoinRequests,
    GetTripInvitationCode,
    GetTripParticipants,
    ListMyTrips,
)
from sillycation.application.transactional import TransactionalCommands
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.value_objects import InvitationCode


logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False, bearerFormat="JWT")


def get_http_authentication(request: Request) -> HttpAuthentication:
    authentication: Optional[HttpAuthentication] = getattr(
        request.app.state, "authentication", None
    )
    if authentication is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Protected API is not configured",
        )
    return authentication


def get_authenticated_user_id(
    request: Request,
    credential: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)],
) -> UserId:
    authentication = get_http_authentication(request)
    if credential is None or len(request.headers.getlist("authorization")) != 1:
        raise authentication_required()
    try:
        user_id = authentication.tokens.verify(credential.credentials)
        exists = get_user_repository(request).get_by_id(user_id) is not None
    except InvalidTokenError:
        raise authentication_required() from None
    except Exception as error:
        logger.error("Identity verification failed (%s)", type(error).__name__)
        raise HTTPException(500, "Internal Server Error") from None
    if not exists:
        raise authentication_required()
    return user_id


@dataclass(frozen=True)
class PersistenceDependencies:
    users: UserRepository
    trips: TripRepository
    episodes: EpisodeRepository
    unit_of_work_factory: Callable[[], UnitOfWork]


def _get_persistence(request: Request) -> PersistenceDependencies:
    persistence: Optional[PersistenceDependencies] = getattr(
        request.app.state, "persistence", None
    )
    if persistence is None:
        raise RuntimeError("Persistence has not been configured by the app lifespan")
    return persistence


def get_trip_repository(request: Request) -> TripRepository:
    return _get_persistence(request).trips


def get_episode_repository(request: Request) -> EpisodeRepository:
    return _get_persistence(request).episodes


def get_user_repository(request: Request) -> UserRepository:
    return _get_persistence(request).users


def get_unit_of_work_factory(request: Request) -> Callable[[], UnitOfWork]:
    return _get_persistence(request).unit_of_work_factory


def get_password_hasher(request: Request) -> PasswordHasher:
    hasher: Optional[PasswordHasher] = getattr(
        request.app.state, "password_hasher", None
    )
    if hasher is None:
        raise RuntimeError("PasswordHasher provider has not been configured")
    return hasher


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


def get_transactional_commands(
    factory: Annotated[Callable[[], UnitOfWork], Depends(get_unit_of_work_factory)],
    passwords: PasswordHasherDependency,
) -> TransactionalCommands:
    return TransactionalCommands(factory, passwords)
