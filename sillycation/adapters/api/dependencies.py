"""Dependency graph for the upcoming read endpoints.

The composition root must override repository providers before wiring routes.
Tests use app.dependency_overrides with the same functions. Nothing opens a DB
at import or app creation time. Missing configuration fails explicitly; no
fake identities or implicit repository instances are provided.

Repository lifetime and write transactions await persistence integration.
Authenticated identity and credential providers belong to step 15.
"""

from typing import Annotated

from fastapi import Depends

from sillycation.application.episode_read_use_cases import (
    GetTripDashboard,
    ListTripEpisodes,
)
from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.application.ranking_use_cases import GetParticipantRanking
from sillycation.application.trip_read_use_cases import (
    GetPendingJoinRequests,
    GetTripInvitationCode,
    GetTripParticipants,
    ListMyTrips,
)


def get_trip_repository() -> TripRepository:
    raise RuntimeError("TripRepository provider has not been configured")


def get_episode_repository() -> EpisodeRepository:
    raise RuntimeError("EpisodeRepository provider has not been configured")


TripRepositoryDependency = Annotated[TripRepository, Depends(get_trip_repository)]
EpisodeRepositoryDependency = Annotated[
    EpisodeRepository, Depends(get_episode_repository)
]


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
