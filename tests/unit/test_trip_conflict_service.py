from copy import deepcopy
from datetime import date

import pytest

from sillycation.domain.identifiers import JoinRequestId, TripId, UserId
from sillycation.domain.services import TripConflictService
from sillycation.domain.trip import Trip, TripStatus
from sillycation.domain.value_objects import InvitationCode, TripPeriod


USER = UserId("user")
OTHER = UserId("other")
CANDIDATE = TripPeriod(date(2026, 10, 10), date(2026, 10, 15))


def make_trip(start=10, end=15, creator=USER):
    return Trip(
        TripId(f"trip-{start}-{end}"),
        "Holiday",
        creator,
        TripPeriod(date(2026, 10, start), date(2026, 10, end)),
        InvitationCode("invite"),
    )


def admit(trip, user):
    request = trip.request_to_join(JoinRequestId(user.value), user)
    trip.approve_join_request(request.id, requested_by=trip.creator_id)


def test_no_existing_trips_means_no_conflict():
    assert TripConflictService().has_trip_conflict(USER, CANDIDATE, []) is False


@pytest.mark.parametrize("status", [TripStatus.PLANNED, TripStatus.ACTIVE])
@pytest.mark.parametrize(
    "start,end,expected",
    [
        (1, 9, False),
        (16, 20, False),
        (1, 10, True),
        (15, 20, True),
        (8, 12, True),
        (12, 18, True),
        (11, 14, True),
        (1, 20, True),
        (10, 15, True),
        (12, 12, True),
    ],
)
def test_period_overlap_for_relevant_statuses(status, start, end, expected):
    trip = make_trip(start, end)
    if status is TripStatus.ACTIVE:
        admit(trip, OTHER)
        trip.activate(requested_by=USER, current_date=trip.period.start_date)

    assert TripConflictService().has_trip_conflict(USER, CANDIDATE, [trip]) is expected


@pytest.mark.parametrize("status", [TripStatus.COMPLETED, TripStatus.ARCHIVED])
def test_completed_and_archived_trips_are_ignored(monkeypatch, status):
    trip = make_trip()
    # These lifecycle transitions are not implemented yet; simulate loaded state.
    monkeypatch.setattr(trip, "_status", status)

    assert TripConflictService().has_trip_conflict(USER, CANDIDATE, [trip]) is False


def test_single_day_candidate_conflicts_on_shared_date():
    candidate = TripPeriod(date(2026, 10, 15), date(2026, 10, 15))
    assert TripConflictService().has_trip_conflict(USER, candidate, [make_trip()])


def test_unrelated_users_trip_is_ignored():
    trip = make_trip(creator=OTHER)
    assert TripConflictService().has_trip_conflict(USER, CANDIDATE, [trip]) is False


def test_pending_application_is_not_participation():
    trip = make_trip(creator=OTHER)
    trip.request_to_join(JoinRequestId("pending"), USER)
    assert TripConflictService().has_trip_conflict(USER, CANDIDATE, [trip]) is False


def test_approved_participant_has_conflict_even_when_not_creator():
    trip = make_trip(creator=OTHER)
    admit(trip, USER)
    assert TripConflictService().has_trip_conflict(USER, CANDIDATE, [trip]) is True


@pytest.mark.parametrize("conflicting", [False, True])
def test_multiple_trips_with_or_without_a_conflict(conflicting):
    trips = [make_trip(1, 5), make_trip(20, 25)]
    if conflicting:
        trips.append(make_trip())
    assert (
        TripConflictService().has_trip_conflict(USER, CANDIDATE, iter(trips))
        is conflicting
    )


@pytest.mark.parametrize("conflicting", [False, True])
def test_check_does_not_mutate_aggregates_or_pending_requests(conflicting):
    candidate_trip = make_trip(creator=OTHER)
    candidate_trip.request_to_join(JoinRequestId("pending"), USER)
    existing = make_trip() if conflicting else make_trip(1, 5)
    trips = [candidate_trip, existing]
    before = [deepcopy(vars(trip)) for trip in trips]

    assert (
        TripConflictService().has_trip_conflict(USER, candidate_trip.period, trips)
        is conflicting
    )

    assert [vars(trip) for trip in trips] == before


def test_rechecking_uses_current_participation():
    trip = make_trip(creator=OTHER)
    request = trip.request_to_join(JoinRequestId("pending"), USER)
    service = TripConflictService()
    assert service.has_trip_conflict(USER, CANDIDATE, [trip]) is False

    trip.approve_join_request(request.id, requested_by=OTHER)

    assert service.has_trip_conflict(USER, CANDIDATE, [trip]) is True
