"""Translate application projections to HTTP models without business decisions.

Use authorized read use cases before mapping: these functions do not filter
drafts, authorize actors, compute rankings or change lifecycle states.
Incoming string IDs are wrapped in the existing domain ID types by the caller;
they remain opaque strings, rather than being restricted to UUIDs.
"""

from typing import Union

from sillycation.adapters.api.schemas.responses import (
    EpisodeResponse,
    InvitationCodeResponse,
    JoinRequestResponse,
    ParticipantResponse,
    RankingEntryResponse,
    RegisteredUserResponse,
    TripDashboardResponse,
    TripResponse,
    TripSummaryResponse,
)
from sillycation.application.episode_read_use_cases import (
    DashboardTrip,
    EpisodeSummary,
    TripDashboard,
)
from sillycation.application.trip_read_use_cases import TripSummary
from sillycation.domain.episode import Episode
from sillycation.domain.identifiers import UserId
from sillycation.domain.services import RankingEntry
from sillycation.domain.trip import JoinRequest, Participant, Trip
from sillycation.domain.value_objects import InvitationCode


def registered_user_response(user_id: UserId) -> RegisteredUserResponse:
    return RegisteredUserResponse(id=user_id.value)


def trip_summary_response(trip: TripSummary) -> TripSummaryResponse:
    return TripSummaryResponse(
        id=trip.id.value,
        name=trip.name,
        creator_id=trip.creator_id.value,
        start_date=trip.period.start_date,
        end_date=trip.period.end_date,
        status=trip.status,
    )


def trip_response(trip: Union[Trip, DashboardTrip]) -> TripResponse:
    return TripResponse(
        id=trip.id.value,
        name=trip.name,
        creator_id=trip.creator_id.value,
        start_date=trip.period.start_date,
        end_date=trip.period.end_date,
        status=trip.status,
        description=trip.description,
    )


def invitation_code_response(code: InvitationCode) -> InvitationCodeResponse:
    return InvitationCodeResponse(invitation_code=code.value)


def participant_response(participant: Participant) -> ParticipantResponse:
    return ParticipantResponse(
        trip_id=participant.trip_id.value, user_id=participant.user_id.value
    )


def join_request_response(request: JoinRequest) -> JoinRequestResponse:
    return JoinRequestResponse(
        id=request.id.value,
        trip_id=request.trip_id.value,
        user_id=request.user_id.value,
        status=request.status,
    )


def episode_response(episode: Union[EpisodeSummary, Episode]) -> EpisodeResponse:
    return EpisodeResponse(
        id=episode.id.value,
        trip_id=episode.trip_id.value,
        author_id=episode.author_id.value,
        protagonist_id=episode.protagonist_id.value,
        title=episode.title,
        description=episode.description,
        date=episode.date,
        status=episode.status,
        score=episode.score,
    )


def ranking_entry_response(entry: RankingEntry) -> RankingEntryResponse:
    return RankingEntryResponse(
        user_id=entry.user_id.value, score=entry.score, position=entry.position
    )


def dashboard_response(dashboard: TripDashboard) -> TripDashboardResponse:
    return TripDashboardResponse(
        trip=trip_response(dashboard.trip),
        participants=[participant_response(item) for item in dashboard.participants],
        episodes=[episode_response(item) for item in dashboard.episodes],
        ranking=[ranking_entry_response(item) for item in dashboard.ranking],
    )
