"""Public projections flatten IDs/periods without leaking aggregate internals."""

from datetime import date
from decimal import Decimal

import pytest

from sillycation.adapters.api.mappers import (
    dashboard_response,
    episode_response,
    invitation_code_response,
    join_request_response,
    participant_response,
    ranking_entry_response,
    registered_user_response,
    trip_response,
    trip_summary_response,
)
from sillycation.application.episode_read_use_cases import (
    DashboardTrip,
    EpisodeSummary,
    TripDashboard,
)
from sillycation.application.trip_read_use_cases import TripSummary
from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.identifiers import EpisodeId, JoinRequestId, TripId, UserId
from sillycation.domain.services import RankingEntry
from sillycation.domain.trip import (
    JoinRequest,
    JoinRequestStatus,
    Participant,
    Trip,
    TripStatus,
)
from sillycation.domain.value_objects import InvitationCode, TripPeriod

DAY = date(2026, 11, 10)
TRIP = TripId("trip-opaque")
USER = UserId("user-opaque")


def make_trip() -> Trip:
    return Trip(TRIP, "Roma", USER, TripPeriod(DAY, DAY), InvitationCode("PRIVATE"))


def test_trip_maps_ids_dates_status_and_optional_description() -> None:
    trip = make_trip()
    before = (trip.status, trip.participants, trip.join_requests)
    result = trip_response(trip).model_dump(mode="json")
    assert result == {
        "id": "trip-opaque",
        "name": "Roma",
        "creator_id": "user-opaque",
        "start_date": "2026-11-10",
        "end_date": "2026-11-10",
        "status": "PLANNED",
        "description": None,
    }
    assert (trip.status, trip.participants, trip.join_requests) == before
    summary = TripSummary(trip.id, trip.name, trip.creator_id, trip.period, trip.status)
    assert trip_summary_response(summary).model_dump(mode="json") == {
        key: value for key, value in result.items() if key != "description"
    }
    assert invitation_code_response(trip.invitation_code).model_dump() == {
        "invitation_code": "PRIVATE"
    }


@pytest.mark.parametrize("status", list(JoinRequestStatus))
def test_membership_and_request_ids_and_enums_are_flattened(status) -> None:
    member = Participant(TRIP, USER)
    assert participant_response(member).model_dump() == {
        "trip_id": "trip-opaque",
        "user_id": "user-opaque",
    }
    request = JoinRequest(JoinRequestId("request"), TRIP, USER, status)
    assert join_request_response(request).model_dump(mode="json") == {
        "id": "request",
        "trip_id": "trip-opaque",
        "user_id": "user-opaque",
        "status": status.value,
    }


@pytest.mark.parametrize("status", list(EpisodeStatus))
def test_episode_projection_preserves_score_and_status(status) -> None:
    score = Decimal("4.5") if status is EpisodeStatus.COMPLETED else None
    summary = EpisodeSummary(
        EpisodeId("episode"), TRIP, USER, USER, "Title", "Details", DAY, status, score
    )
    result = episode_response(summary).model_dump(mode="json")
    assert result == {
        "id": "episode",
        "trip_id": "trip-opaque",
        "author_id": "user-opaque",
        "protagonist_id": "user-opaque",
        "title": "Title",
        "description": "Details",
        "date": "2026-11-10",
        "status": status.value,
        "score": "4.5" if score is not None else None,
    }
    assert "votes" not in result


def test_episode_aggregate_can_be_mapped_without_changing_it() -> None:
    episode = Episode(EpisodeId("draft"), TRIP, USER, USER, "Title", "Details", DAY)
    assert episode_response(episode).score is None
    assert episode.status is EpisodeStatus.DRAFT
    assert episode.votes == ()


@pytest.mark.parametrize("status", list(TripStatus))
def test_dashboard_maps_authorized_projection_without_recomputing_it(status) -> None:
    trip = DashboardTrip(TRIP, "Roma", USER, TripPeriod(DAY, DAY), status, "Details")
    # The application has already selected visible episodes and computed ranking.
    ranking = RankingEntry(USER, Decimal("0"), 1)
    dashboard = TripDashboard(trip, (Participant(TRIP, USER),), (), (ranking,))
    result = dashboard_response(dashboard).model_dump(mode="json")
    assert result["trip"]["status"] == status.value
    assert result["trip"]["description"] == "Details"
    assert result["participants"] == [
        {"trip_id": "trip-opaque", "user_id": "user-opaque"}
    ]
    assert result["episodes"] == []
    assert result["ranking"] == [
        {"user_id": "user-opaque", "score": "0", "position": 1}
    ]
    assert ranking_entry_response(ranking).score == Decimal("0")


def test_registration_response_contains_only_identity() -> None:
    assert registered_user_response(USER).model_dump() == {"id": "user-opaque"}
