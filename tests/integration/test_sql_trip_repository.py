"""SqlAlchemyTripRepository against a real SQLite database."""

from datetime import date

import pytest
from sqlalchemy import Engine

from sillycation.adapters.persistence.database import create_database
from sillycation.adapters.persistence.trip_repository import SqlAlchemyTripRepository
from sillycation.application.ports.repositories import TripRepository
from sillycation.domain.errors import InvalidState
from sillycation.domain.identifiers import JoinRequestId, TripId, UserId
from sillycation.domain.trip import (
    JoinRequest,
    JoinRequestStatus,
    Participant,
    Trip,
    TripStatus,
)
from sillycation.domain.value_objects import InvitationCode, TripPeriod


CREATOR = UserId("creator")
MEMBER = UserId("member")
APPLICANT = UserId("applicant")
START = date(2026, 11, 10)
END = date(2026, 11, 12)


@pytest.fixture
def trips(engine: Engine) -> TripRepository:
    return SqlAlchemyTripRepository(engine)


def make_trip(key: str = "trip", status: TripStatus = TripStatus.PLANNED) -> Trip:
    """Build a trip with two participants, moved forward to the given status."""
    trip = Trip(
        TripId(key),
        f"Trip {key}",
        CREATOR,
        TripPeriod(START, END),
        InvitationCode(f"CODE-{key}"),
        "A description",
    )
    trip.request_to_join(JoinRequestId(f"{key}-member"), MEMBER)
    trip.approve_join_request(JoinRequestId(f"{key}-member"), requested_by=CREATOR)
    if status is not TripStatus.PLANNED:
        trip.activate(requested_by=CREATOR, current_date=START)
    if status in (TripStatus.COMPLETED, TripStatus.ARCHIVED):
        trip.complete(
            requested_by=CREATOR, current_date=END, has_unresolved_episodes=False
        )
    if status is TripStatus.ARCHIVED:
        trip.archive(requested_by=CREATOR)
    return trip


def assert_same_trip(loaded: Trip, original: Trip) -> None:
    assert loaded.id == original.id
    assert loaded.name == original.name
    assert loaded.description == original.description
    assert loaded.creator_id == original.creator_id
    assert loaded.period == original.period
    assert loaded.invitation_code == original.invitation_code
    assert loaded.status is original.status
    assert loaded.participants == original.participants
    assert set(loaded.join_requests) == set(original.join_requests)


@pytest.mark.parametrize("status", list(TripStatus))
def test_trip_is_saved_and_loaded_in_every_status(
    trips: TripRepository, status: TripStatus
) -> None:
    trip = make_trip(status=status)

    trips.save(trip)
    loaded = trips.get_by_id(trip.id)

    assert loaded is not None
    assert_same_trip(loaded, trip)


def test_trip_without_description_is_saved_and_loaded(trips: TripRepository) -> None:
    trip = Trip(
        TripId("plain"), "Plain", CREATOR, TripPeriod(START, END), InvitationCode("P")
    )

    trips.save(trip)
    loaded = trips.get_by_id(trip.id)

    assert loaded is not None
    assert loaded.description is None
    assert loaded.participants == {Participant(trip.id, CREATOR)}
    assert loaded.join_requests == ()


def test_join_requests_are_loaded_with_their_status(trips: TripRepository) -> None:
    trip = make_trip()
    trip.request_to_join(JoinRequestId("pending"), APPLICANT)
    trips.save(trip)

    loaded = trips.get_by_id(trip.id)

    assert loaded is not None
    assert loaded.get_join_request(JoinRequestId("pending")) == JoinRequest(
        JoinRequestId("pending"), trip.id, APPLICANT, JoinRequestStatus.PENDING
    )
    assert (
        loaded.get_join_request(JoinRequestId("trip-member")).status
        is JoinRequestStatus.APPROVED
    )


def test_saving_again_replaces_the_stored_trip(trips: TripRepository) -> None:
    trip = make_trip()
    trip.request_to_join(JoinRequestId("pending"), APPLICANT)
    trips.save(trip)

    trip.approve_join_request(JoinRequestId("pending"), requested_by=CREATOR)
    trip.activate(requested_by=CREATOR, current_date=START)
    trips.save(trip)
    loaded = trips.get_by_id(trip.id)

    assert loaded is not None
    assert_same_trip(loaded, trip)
    assert loaded.status is TripStatus.ACTIVE
    assert Participant(trip.id, APPLICANT) in loaded.participants


def test_loaded_trip_still_enforces_its_rules(trips: TripRepository) -> None:
    trips.save(make_trip(status=TripStatus.ACTIVE))

    loaded = trips.get_by_id(TripId("trip"))

    assert loaded is not None
    with pytest.raises(InvalidState):
        loaded.request_to_join(JoinRequestId("late"), APPLICANT)


def test_unknown_trip_is_not_found(trips: TripRepository) -> None:
    assert trips.get_by_id(TripId("missing")) is None
    assert trips.get_by_invitation_code(InvitationCode("missing")) is None


def test_trip_is_found_by_invitation_code(trips: TripRepository) -> None:
    trips.save(make_trip("first"))
    trips.save(make_trip("second"))

    found = trips.get_by_invitation_code(InvitationCode("CODE-second"))

    assert found is not None
    assert found.id == TripId("second")


def test_find_by_participant_returns_only_trips_with_actual_membership(
    trips: TripRepository,
) -> None:
    joined = make_trip("joined")
    requested = make_trip("requested")
    requested.request_to_join(JoinRequestId("pending"), APPLICANT)
    joined.request_to_join(JoinRequestId("accepted"), APPLICANT)
    joined.approve_join_request(JoinRequestId("accepted"), requested_by=CREATOR)
    trips.save(joined)
    trips.save(requested)

    found = trips.find_by_participant(APPLICANT)

    assert [trip.id for trip in found] == [TripId("joined")]
    assert_same_trip(found[0], joined)
    assert trips.find_by_participant(UserId("stranger")) == []


def test_find_by_participant_returns_trips_in_any_status(
    trips: TripRepository,
) -> None:
    for status in TripStatus:
        trips.save(make_trip(status.value, status))

    found = trips.find_by_participant(MEMBER)

    assert {trip.status for trip in found} == set(TripStatus)


def test_find_active_or_planned_excludes_completed_and_archived_trips(
    trips: TripRepository,
) -> None:
    for status in TripStatus:
        trips.save(make_trip(status.value, status))

    found = trips.find_active_or_planned_trips_by_participant(MEMBER)

    assert {trip.status for trip in found} == {TripStatus.PLANNED, TripStatus.ACTIVE}
    assert trips.find_active_or_planned_trips_by_participant(UserId("stranger")) == []


def test_trips_survive_an_application_restart(database_url: str) -> None:
    trip = make_trip(status=TripStatus.ACTIVE)
    first_run = create_database(database_url)
    SqlAlchemyTripRepository(first_run).save(trip)
    first_run.dispose()

    second_run = create_database(database_url)
    loaded = SqlAlchemyTripRepository(second_run).get_by_id(trip.id)
    second_run.dispose()

    assert loaded is not None
    assert_same_trip(loaded, trip)
