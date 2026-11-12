from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
from datetime import date
from typing import Optional, Sequence

import pytest

from sillycation.application.ports.repositories import TripRepository
from sillycation.application.trip_read_use_cases import (
    GetTripInvitationCode,
    GetPendingJoinRequests,
    GetTripParticipants,
    ListMyTrips,
    TripSummary,
)
from sillycation.domain.identifiers import TripId, UserId, JoinRequestId
from sillycation.domain.trip import Trip, TripStatus, Participant
from sillycation.domain.value_objects import InvitationCode, TripPeriod

CREATOR = UserId("creator")
MEMBER = UserId("member")
PENDING = UserId("pending")
OUTSIDER = UserId("outsider")
DAY = date(2026, 11, 12)
READS = (GetTripInvitationCode, GetPendingJoinRequests, GetTripParticipants)


class MemoryTrips:
    def __init__(self, trips: Sequence[Trip] = ()) -> None:
        self.trips = list(trips)
        self.lookups: list[TripId] = []
        self.queries: list[UserId] = []

    def get_by_id(self, trip_id: TripId) -> Optional[Trip]:
        self.lookups.append(trip_id)
        return next((t for t in self.trips if t.id == trip_id), None)

    def find_by_participant(self, user_id: UserId) -> Sequence[Trip]:
        self.queries.append(user_id)
        # Deliberately unfiltered to exercise defensive membership filtering.
        return self.trips

    def save(self, trip: Trip) -> Trip:
        raise AssertionError("Reads must not save Trip")

    def get_by_invitation_code(self, invitation_code: InvitationCode) -> Optional[Trip]:
        raise AssertionError("Unexpected invitation lookup")

    def find_active_or_planned_trips_by_participant(
        self, user_id: UserId
    ) -> Sequence[Trip]:
        raise AssertionError("Unexpected overlap query")


def make_trip(key="trip", status=TripStatus.PLANNED, creator=CREATOR, pending=True):
    trip = Trip(
        TripId(key),
        "Holiday " + key,
        creator,
        TripPeriod(DAY, DAY),
        InvitationCode("secret-" + key),
    )
    trip.request_to_join(JoinRequestId("approved"), MEMBER)
    trip.approve_join_request(JoinRequestId("approved"), requested_by=creator)
    trip.request_to_join(JoinRequestId("rejected"), UserId("rejected"))
    trip.reject_join_request(JoinRequestId("rejected"), requested_by=creator)
    if pending:
        trip.request_to_join(JoinRequestId("z-pending"), PENDING)
        trip.request_to_join(JoinRequestId("a-pending"), UserId("another"))
    if status is not TripStatus.PLANNED:
        trip.activate(requested_by=creator, current_date=DAY)
    if status in (TripStatus.COMPLETED, TripStatus.ARCHIVED):
        trip.complete(
            requested_by=creator, current_date=DAY, has_unresolved_episodes=False
        )
    if status is TripStatus.ARCHIVED:
        trip.archive(requested_by=creator)
    return trip


@pytest.mark.parametrize("status", list(TripStatus))
def test_authorized_reads_in_every_state_without_mutations(status: TripStatus) -> None:
    trip = make_trip(status=status)
    trips = MemoryTrips([make_trip("other"), trip])
    port: TripRepository = trips
    before = deepcopy(vars(trip))
    assert GetTripInvitationCode(port).execute(
        trip_id=trip.id, requested_by=CREATOR
    ) == InvitationCode("secret-trip")
    requests = GetPendingJoinRequests(port).execute(
        trip_id=trip.id, requested_by=CREATOR
    )
    assert requests == (
        trip.get_join_request(JoinRequestId("a-pending")),
        trip.get_join_request(JoinRequestId("z-pending")),
    )
    assert isinstance(requests, tuple)
    with pytest.raises(FrozenInstanceError):
        setattr(requests[0], "user_id", OUTSIDER)
    for actor in (CREATOR, MEMBER):
        participants = GetTripParticipants(port).execute(
            trip_id=trip.id, requested_by=actor
        )
        assert participants == (
            Participant(trip.id, CREATOR),
            Participant(trip.id, MEMBER),
        )
        with pytest.raises(FrozenInstanceError):
            setattr(participants[0], "user_id", OUTSIDER)
    assert trips.lookups == [trip.id] * 4
    assert trips.queries == []
    assert vars(trip) == before


@pytest.mark.parametrize("use_case", [GetTripInvitationCode, GetPendingJoinRequests])
@pytest.mark.parametrize("actor", [MEMBER, OUTSIDER, PENDING])
def test_creator_only_reads_reject_other_actors(use_case, actor):
    trip = make_trip()
    trips = MemoryTrips([trip])
    before = deepcopy(vars(trip))
    with pytest.raises(PermissionError):
        use_case(trips).execute(trip_id=trip.id, requested_by=actor)
    assert vars(trip) == before
    assert trips.lookups == [trip.id]
    assert trips.queries == []


@pytest.mark.parametrize("status", list(TripStatus))
@pytest.mark.parametrize("actor", [OUTSIDER, PENDING])
def test_participant_read_excludes_non_members(status, actor):
    trip = make_trip(status=status)
    before = deepcopy(vars(trip))
    with pytest.raises(PermissionError):
        GetTripParticipants(MemoryTrips([trip])).execute(
            trip_id=trip.id, requested_by=actor
        )
    assert vars(trip) == before


@pytest.mark.parametrize("use_case", READS)
def test_missing_trip_is_lookup_error(use_case):
    trips = MemoryTrips([make_trip("other")])
    with pytest.raises(LookupError, match="Trip"):
        use_case(trips).execute(trip_id=TripId("missing"), requested_by=CREATOR)
    assert trips.lookups == [TripId("missing")]


def test_no_pending_requests_returns_empty_tuple():
    trip = make_trip(pending=False)
    before = deepcopy(vars(trip))
    assert (
        GetPendingJoinRequests(MemoryTrips([trip])).execute(
            trip_id=trip.id, requested_by=CREATOR
        )
        == ()
    )
    assert vars(trip) == before


@pytest.mark.parametrize("archived", [False, True])
def test_listing_filters_membership_and_states_without_extra_queries(
    archived: bool,
) -> None:
    planned = make_trip("b-planned")
    active = make_trip("a-active", TripStatus.ACTIVE)
    completed = make_trip("c-completed", TripStatus.COMPLETED)
    history = make_trip("d-archived", TripStatus.ARCHIVED)
    foreign = make_trip("foreign", creator=OUTSIDER)
    # CREATOR has only a pending request in this Trip.
    foreign.request_to_join(JoinRequestId("creator-pending"), CREATOR)
    unrelated = make_trip("unrelated", creator=OUTSIDER)
    if archived:
        for excluded in (foreign, unrelated):
            excluded.activate(requested_by=OUTSIDER, current_date=DAY)
            excluded.complete(
                requested_by=OUTSIDER, current_date=DAY, has_unresolved_episodes=False
            )
            excluded.archive(requested_by=OUTSIDER)
    stored = [history, completed, foreign, planned, unrelated, active]
    trips = MemoryTrips(stored)
    port: TripRepository = trips
    before = deepcopy([vars(t) for t in stored])
    use_case = ListMyTrips(port)
    result = use_case.execute(requested_by=CREATOR, archived=archived)
    expected_trips = [history] if archived else [active, planned, completed]
    expected = tuple(
        TripSummary(t.id, t.name, t.creator_id, t.period, t.status)
        for t in expected_trips
    )
    assert result == expected
    assert isinstance(result, tuple)
    assert trips.queries == [CREATOR]
    assert trips.lookups == []
    for summary in result:
        assert set(asdict(summary)) == {"id", "name", "creator_id", "period", "status"}
        with pytest.raises(FrozenInstanceError):
            setattr(summary, "name", "Changed")
    assert [vars(t) for t in stored] == before
    trips.trips.reverse()
    assert use_case.execute(requested_by=CREATOR, archived=archived) == expected
    if not archived:
        assert use_case.execute(requested_by=CREATOR) == expected


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("contents", ["empty", "other_mode", "nonmember"])
def test_listing_no_matches_returns_empty_tuple(archived, contents):
    matching = TripStatus.ARCHIVED if archived else TripStatus.PLANNED
    other = TripStatus.PLANNED if archived else TripStatus.ARCHIVED
    trip = make_trip(status=matching if contents == "nonmember" else other)
    trips = MemoryTrips([] if contents == "empty" else [trip])
    actor = OUTSIDER if contents == "nonmember" else CREATOR
    assert ListMyTrips(trips).execute(requested_by=actor, archived=archived) == ()
    assert trips.queries == [actor]
    assert trips.lookups == []


def test_listing_includes_approved_non_creator():
    trip = make_trip()
    result = ListMyTrips(MemoryTrips([trip])).execute(requested_by=MEMBER)
    assert tuple(row.id for row in result) == (trip.id,)


@pytest.mark.parametrize("use_case", [*READS, ListMyTrips])
def test_repository_errors_propagate_unchanged(use_case, monkeypatch):
    trip = make_trip()
    trips = MemoryTrips([trip])
    before = deepcopy(vars(trip))
    failure = RuntimeError("Storage unavailable")

    def fail(*args):
        raise failure

    listing = use_case is ListMyTrips
    monkeypatch.setattr(trips, "find_by_participant" if listing else "get_by_id", fail)
    args = {"requested_by": CREATOR}
    if not listing:
        args["trip_id"] = trip.id
    with pytest.raises(RuntimeError) as caught:
        use_case(trips).execute(**args)
    assert caught.value is failure
    assert vars(trip) == before
