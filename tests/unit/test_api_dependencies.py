"""Composition and FastAPI overrides using test-only routes and repository mocks."""

from datetime import date
from typing import Annotated
from unittest.mock import Mock

from fastapi import Depends, Request
from fastapi.testclient import TestClient
import pytest

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api.dependencies import (
    get_episode_repository,
    get_list_my_trips,
    get_participant_ranking,
    get_pending_join_requests,
    get_trip_dashboard,
    get_trip_episodes,
    get_trip_invitation_code,
    get_trip_participants,
    get_trip_repository,
)
from sillycation.adapters.api.mappers import dashboard_response
from sillycation.adapters.api.schemas.responses import TripDashboardResponse
from sillycation.application.episode_read_use_cases import GetTripDashboard
from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.domain.identifiers import TripId, UserId
from sillycation.domain.trip import Trip
from sillycation.domain.value_objects import InvitationCode, TripPeriod


def repository_mocks() -> tuple[Mock, Mock, Trip]:
    trip = Trip(
        TripId("trip"),
        "Roma",
        UserId("creator"),
        TripPeriod(date(2026, 11, 10), date(2026, 11, 12)),
        InvitationCode("CODE"),
    )
    trips = Mock(spec=TripRepository)
    trips.get_by_id.return_value = trip
    trips.find_by_participant.return_value = [trip]
    episodes = Mock(spec=EpisodeRepository)
    episodes.find_by_trip.return_value = []
    return trips, episodes, trip


@pytest.mark.parametrize("provider", [get_trip_repository, get_episode_repository])
def test_missing_repository_configuration_fails_explicitly(provider) -> None:
    with pytest.raises(RuntimeError, match="has not been configured"):
        provider(Request({"type": "http", "app": create_app()}))


def test_read_providers_construct_existing_use_cases_with_supplied_ports() -> None:
    trips, episodes, trip = repository_mocks()
    actor = trip.creator_id
    assert get_list_my_trips(trips).execute(requested_by=actor)[0].id == trip.id
    assert (
        get_trip_invitation_code(trips).execute(trip_id=trip.id, requested_by=actor)
        == trip.invitation_code
    )
    assert (
        get_pending_join_requests(trips).execute(trip_id=trip.id, requested_by=actor)
        == ()
    )
    assert get_trip_participants(trips).execute(
        trip_id=trip.id, requested_by=actor
    ) == tuple(trip.participants)
    assert (
        get_trip_episodes(trips, episodes).execute(trip_id=trip.id, requested_by=actor)
        == ()
    )
    assert (
        get_participant_ranking(trips, episodes)
        .execute(trip_id=trip.id, requested_by=actor)[0]
        .user_id
        == actor
    )
    assert (
        get_trip_dashboard(trips, episodes)
        .execute(trip_id=trip.id, requested_by=actor)
        .trip.id
        == trip.id
    )
    trips.save.assert_not_called()
    episodes.save.assert_not_called()


def test_fastapi_can_override_repository_dependencies_per_application(tmp_path) -> None:
    trips, episodes, trip = repository_mocks()
    app = create_app(database_url=f"sqlite:///{tmp_path / 'api.db'}")

    @app.get("/probe", response_model=TripDashboardResponse)
    def probe(
        use_case: Annotated[GetTripDashboard, Depends(get_trip_dashboard)],
    ) -> TripDashboardResponse:
        return dashboard_response(
            use_case.execute(trip_id=trip.id, requested_by=trip.creator_id)
        )

    app.dependency_overrides[get_trip_repository] = lambda: trips
    app.dependency_overrides[get_episode_repository] = lambda: episodes
    with TestClient(app) as client:
        response = client.get("/probe")
    assert response.status_code == 200
    assert response.json()["trip"]["id"] == "trip"
    trips.get_by_id.assert_called_once_with(trip.id)
    episodes.find_by_trip.assert_called_once_with(trip.id)
    assert create_app().dependency_overrides == {}
    assert create_app().openapi()["paths"] == {}


def test_fastapi_can_override_an_entire_use_case(tmp_path) -> None:
    trips, episodes, trip = repository_mocks()
    use_case = Mock(spec=GetTripDashboard)
    use_case.execute.return_value = get_trip_dashboard(trips, episodes).execute(
        trip_id=trip.id, requested_by=trip.creator_id
    )
    app = create_app(database_url=f"sqlite:///{tmp_path / 'api.db'}")

    @app.get("/probe", response_model=TripDashboardResponse)
    def probe(
        dependency: Annotated[GetTripDashboard, Depends(get_trip_dashboard)],
    ) -> TripDashboardResponse:
        return dashboard_response(
            dependency.execute(trip_id=trip.id, requested_by=trip.creator_id)
        )

    # Overriding the use case bypasses its repository dependencies.
    app.dependency_overrides[get_trip_dashboard] = lambda: use_case
    with TestClient(app) as client:
        assert client.get("/probe").status_code == 200
    use_case.execute.assert_called_once_with(
        trip_id=trip.id, requested_by=trip.creator_id
    )
