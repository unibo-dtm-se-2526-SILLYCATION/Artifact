from copy import deepcopy
from datetime import date
from typing import Optional, Sequence

import pytest

from sillycation.application.ports.repositories import (
    EpisodeRepository,
    TripRepository,
    UserRepository,
)
from sillycation.application.trip_use_cases import (
    ActivateTrip,
    CompleteTrip,
    ArchiveTrip,
    ApplicationError,
    ApproveJoinRequest,
    CreateTrip,
    RejectJoinRequest,
    RequestJoinTrip,
)
from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.trip import JoinRequestStatus, Participant, Trip, TripStatus
from sillycation.domain.user import User
from sillycation.domain.value_objects import InvitationCode, TripPeriod, VoteValue


CREATOR = UserId("creator")
APPLICANT = UserId("applicant")
DAY = date(2026, 10, 28)
END = date(2026, 10, 30)
REQUEST = JoinRequestId("request")


class MemoryTrips:
    """Detached reads make a missing save observable in these tests."""

    def __init__(self, trips: Sequence[Trip] = ()) -> None:
        self.stored = {trip.id: deepcopy(trip) for trip in trips}
        self.saved: list[TripId] = []
        self.queries: list[UserId] = []

    def save(self, trip: Trip) -> Trip:
        self.stored[trip.id] = deepcopy(trip)
        self.saved.append(trip.id)
        return deepcopy(trip)

    def get_by_id(self, trip_id: TripId) -> Optional[Trip]:
        return deepcopy(self.stored.get(trip_id))

    def get_by_invitation_code(self, invitation_code: InvitationCode) -> Optional[Trip]:
        return next(
            (
                deepcopy(t)
                for t in self.stored.values()
                if t.invitation_code == invitation_code
            ),
            None,
        )

    def find_by_participant(self, user_id: UserId) -> Sequence[Trip]:
        return [
            deepcopy(t)
            for t in self.stored.values()
            if Participant(t.id, user_id) in t.participants
        ]

    def find_active_or_planned_trips_by_participant(
        self, user_id: UserId
    ) -> Sequence[Trip]:
        self.queries.append(user_id)
        return [
            t
            for t in self.find_by_participant(user_id)
            if t.status in (TripStatus.PLANNED, TripStatus.ACTIVE)
        ]


class MemoryUsers:
    def __init__(self) -> None:
        self.users = {CREATOR: User(CREATOR, "Creator", "creator@example.org", "hash")}

    def save(self, user: User) -> User:
        self.users[user.id] = user
        return user

    def get_by_id(self, user_id: UserId) -> Optional[User]:
        return self.users.get(user_id)

    def get_by_username(self, username: str) -> Optional[User]:
        return next((u for u in self.users.values() if u.username == username), None)

    def get_by_email(self, email: str) -> Optional[User]:
        return next((u for u in self.users.values() if u.email == email), None)

    def exists_by_username(self, username: str) -> bool:
        return self.get_by_username(username) is not None

    def exists_by_email(self, email: str) -> bool:
        return self.get_by_email(email) is not None


def make_trip(key="trip", creator=CREATOR, start=DAY, end=END):
    return Trip(
        TripId(key), "Holiday", creator, TripPeriod(start, end), InvitationCode(key)
    )


def admit(trip, user=APPLICANT):
    request = trip.request_to_join(JoinRequestId(user.value), user)
    trip.approve_join_request(request.id, requested_by=trip.creator_id)


@pytest.fixture
def trip():
    return make_trip()


@pytest.fixture
def pending(trip):
    trip.request_to_join(REQUEST, APPLICANT)
    return trip


@pytest.fixture
def creation_data():
    return dict(
        trip_id=TripId("new"),
        name="Autumn",
        creator_id=CREATOR,
        start_date=DAY,
        end_date=END,
        invitation_code=InvitationCode("new"),
        description="Holiday together",
    )


def test_create_trip_persists_creator_membership_and_supplied_values(
    creation_data,
) -> None:
    trips = MemoryTrips()
    users = MemoryUsers()
    # Typed assignments verify that test doubles satisfy the production ports.
    trip_port: TripRepository = trips
    user_port: UserRepository = users
    result = CreateTrip(trip_port, user_port).execute(**creation_data)
    stored = trips.get_by_id(result.id)
    assert stored is not None
    assert stored.status is TripStatus.PLANNED
    assert stored.participants == frozenset({Participant(result.id, CREATOR)})
    assert stored.period == TripPeriod(DAY, END)
    assert stored.name == "Autumn"
    assert stored.description == "Holiday together"
    assert stored.invitation_code == creation_data["invitation_code"]
    assert result.id == creation_data["trip_id"]
    assert trips.saved == [result.id]
    assert trips.queries == [CREATOR]


def test_create_requires_existing_creator(creation_data):
    trips = MemoryTrips()
    creation_data["creator_id"] = UserId("missing")
    with pytest.raises(LookupError, match="User"):
        CreateTrip(trips, MemoryUsers()).execute(**creation_data)
    assert trips.saved == []


def test_create_rejects_invalid_period(creation_data):
    trips = MemoryTrips()
    creation_data["end_date"] = date(2026, 10, 27)
    with pytest.raises(ValueError, match="start date"):
        CreateTrip(trips, MemoryUsers()).execute(**creation_data)
    assert trips.saved == []


@pytest.mark.parametrize("status", [TripStatus.PLANNED, TripStatus.ACTIVE])
def test_create_checks_creator_conflicts(creation_data, status):
    other = make_trip("other")
    if status is TripStatus.ACTIVE:
        admit(other)
        other.activate(requested_by=CREATOR, current_date=DAY)
    trips = MemoryTrips([other])
    with pytest.raises(ApplicationError, match="overlap"):
        CreateTrip(trips, MemoryUsers()).execute(**creation_data)
    assert trips.saved == []


@pytest.mark.parametrize(
    "field,value",
    [("trip_id", TripId("other")), ("invitation_code", InvitationCode("other"))],
)
def test_create_does_not_reuse_identity_or_invitation(creation_data, field, value):
    other = make_trip("other", creator=APPLICANT)
    trips = MemoryTrips([other])
    creation_data[field] = value
    with pytest.raises(ApplicationError, match="already"):
        CreateTrip(trips, MemoryUsers()).execute(**creation_data)
    assert trips.saved == []
    assert trips.stored[other.id].creator_id == APPLICANT


def test_request_join_persists_pending_request_without_membership(trip):
    trips = MemoryTrips(
        [trip, make_trip("past", APPLICANT, date(2026, 10, 1), date(2026, 10, 2))]
    )
    result = RequestJoinTrip(trips).execute(
        invitation_code=trip.invitation_code, request_id=REQUEST, user_id=APPLICANT
    )
    assert result.status is JoinRequestStatus.PENDING
    assert result.user_id == APPLICANT
    assert result.id == REQUEST
    assert trips.stored[trip.id].get_join_request(REQUEST) == result
    assert Participant(trip.id, APPLICANT) not in trips.stored[trip.id].participants
    assert trips.saved == [trip.id]
    assert trips.queries == [APPLICANT]


def test_request_unknown_invitation():
    trips = MemoryTrips()
    with pytest.raises(LookupError, match="invitation"):
        RequestJoinTrip(trips).execute(
            invitation_code=InvitationCode("missing"),
            request_id=REQUEST,
            user_id=APPLICANT,
        )
    assert trips.saved == []
    assert trips.queries == []


@pytest.mark.parametrize("status", [TripStatus.PLANNED, TripStatus.ACTIVE])
def test_request_overlap_has_no_side_effects(trip, status):
    other = make_trip("other", APPLICANT)
    if status is TripStatus.ACTIVE:
        admit(other, CREATOR)
        other.activate(requested_by=APPLICANT, current_date=DAY)
    trips = MemoryTrips([trip, other])
    with pytest.raises(ApplicationError, match="overlap"):
        RequestJoinTrip(trips).execute(
            invitation_code=trip.invitation_code, request_id=REQUEST, user_id=APPLICANT
        )
    assert trips.saved == []
    assert trips.stored[trip.id].join_requests == ()


@pytest.mark.parametrize("invalid", ["member", "duplicate", "active"])
def test_request_delegates_local_invariants(trip, invalid):
    if invalid == "member":
        admit(trip)
    elif invalid == "duplicate":
        trip.request_to_join(JoinRequestId("first"), APPLICANT)
    else:
        admit(trip, UserId("guest"))
        trip.activate(requested_by=CREATOR, current_date=DAY)
    trips = MemoryTrips([trip])
    before = deepcopy(vars(trips.stored[trip.id]))
    with pytest.raises(ValueError):
        RequestJoinTrip(trips).execute(
            invitation_code=trip.invitation_code, request_id=REQUEST, user_id=APPLICANT
        )
    assert trips.saved == []
    assert vars(trips.stored[trip.id]) == before


@pytest.mark.parametrize("conflict", [False, True])
def test_approval_rechecks_and_persists_decision(trip, conflict):
    trips = MemoryTrips([trip])
    RequestJoinTrip(trips).execute(
        invitation_code=trip.invitation_code, request_id=REQUEST, user_id=APPLICANT
    )
    # A conflicting membership can appear between request and approval.
    if conflict:
        other = make_trip("other", APPLICANT)
        trips.save(other)
    trips.saved.clear()
    trips.queries.clear()
    result = ApproveJoinRequest(trips).execute(
        trip_id=trip.id, request_id=REQUEST, requested_by=CREATOR
    )
    expected = JoinRequestStatus.REJECTED if conflict else JoinRequestStatus.APPROVED
    assert result.status is expected
    assert trips.stored[trip.id].get_join_request(REQUEST) == result
    assert (
        Participant(trip.id, APPLICANT) in trips.stored[trip.id].participants
    ) is not conflict
    assert trips.saved == [trip.id]
    assert trips.queries == [APPLICANT]


@pytest.mark.parametrize("use_case", [ApproveJoinRequest, RejectJoinRequest])
@pytest.mark.parametrize(
    "invalid", ["unauthorized", "missing", "approved", "rejected", "active"]
)
def test_decisions_delegate_invariants_without_saving(pending, use_case, invalid):
    actor = CREATOR
    request_id = REQUEST
    if invalid == "unauthorized":
        actor = APPLICANT
    elif invalid == "missing":
        request_id = JoinRequestId("missing")
    elif invalid == "approved":
        pending.approve_join_request(REQUEST, requested_by=CREATOR)
    elif invalid == "rejected":
        pending.reject_join_request(REQUEST, requested_by=CREATOR)
    else:
        admit(pending, UserId("guest"))
        pending.activate(requested_by=CREATOR, current_date=DAY)
    trips = MemoryTrips([pending])
    before = deepcopy(vars(trips.stored[pending.id]))
    with pytest.raises(ValueError):
        use_case(trips).execute(
            trip_id=pending.id, request_id=request_id, requested_by=actor
        )
    assert trips.saved == []
    assert vars(trips.stored[pending.id]) == before


def test_unauthorized_approval_cannot_reject_even_when_conflicting(pending):
    trips = MemoryTrips([pending, make_trip("other", APPLICANT)])
    with pytest.raises(ValueError, match="creator"):
        ApproveJoinRequest(trips).execute(
            trip_id=pending.id, request_id=REQUEST, requested_by=APPLICANT
        )
    assert trips.saved == []
    assert (
        trips.stored[pending.id].get_join_request(REQUEST).status
        is JoinRequestStatus.PENDING
    )


def test_explicit_rejection_persists_without_querying_conflicts(pending):
    trips = MemoryTrips([pending])
    result = RejectJoinRequest(trips).execute(
        trip_id=pending.id, request_id=REQUEST, requested_by=CREATOR
    )
    assert result.status is JoinRequestStatus.REJECTED
    assert trips.stored[pending.id].get_join_request(REQUEST) == result
    assert (
        Participant(pending.id, APPLICANT) not in trips.stored[pending.id].participants
    )
    assert trips.saved == [pending.id]
    assert trips.queries == []


@pytest.mark.parametrize(
    "use_case", [ApproveJoinRequest, RejectJoinRequest, ActivateTrip]
)
def test_missing_trip_is_an_explicit_application_lookup_error(use_case):
    trips = MemoryTrips()
    args = dict(trip_id=TripId("missing"), requested_by=CREATOR)
    if use_case is ActivateTrip:
        args["current_date"] = DAY
    else:
        args["request_id"] = REQUEST
    with pytest.raises(LookupError, match="Trip"):
        use_case(trips).execute(**args)
    assert trips.saved == []


def test_activate_persists_active_trip(trip):
    admit(trip)
    trips = MemoryTrips([trip])
    result = ActivateTrip(trips).execute(
        trip_id=trip.id, requested_by=CREATOR, current_date=DAY
    )
    assert result.status is TripStatus.ACTIVE
    assert trips.stored[trip.id].status is TripStatus.ACTIVE
    assert trips.stored[trip.id].participants == trip.participants
    assert trips.saved == [trip.id]


@pytest.mark.parametrize(
    "invalid", ["unauthorized", "one_member", "too_early", "active"]
)
def test_activate_delegates_invariants_without_saving(trip, invalid):
    actor = APPLICANT if invalid == "unauthorized" else CREATOR
    today = date(2026, 10, 27) if invalid == "too_early" else DAY
    if invalid != "one_member":
        admit(trip)
    if invalid == "active":
        trip.activate(requested_by=CREATOR, current_date=DAY)
    trips = MemoryTrips([trip])
    with pytest.raises(ValueError):
        ActivateTrip(trips).execute(
            trip_id=trip.id, requested_by=actor, current_date=today
        )
    assert trips.saved == []
    assert trips.stored[trip.id].status is trip.status


class CompletionEpisodes:
    def __init__(self, episodes: Sequence[Episode] = ()) -> None:
        self.stored = list(episodes)
        self.queries: list[TripId] = []

    def find_unresolved_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        self.queries.append(trip_id)
        return [
            deepcopy(e)
            for e in self.stored
            if e.trip_id == trip_id
            and e.status
            in (EpisodeStatus.DRAFT, EpisodeStatus.SUBMITTED, EpisodeStatus.VOTING)
        ]

    def save(self, episode: Episode) -> Episode:
        raise AssertionError("Completion must not save Episodes")

    def delete(self, episode_id: EpisodeId) -> None:
        raise AssertionError("Completion must not delete Episodes")

    def get_by_id(self, episode_id: EpisodeId) -> Optional[Episode]:
        raise AssertionError("Unexpected lookup")

    def find_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        raise AssertionError("Unexpected listing")


def lifecycle_trip(status=TripStatus.ACTIVE):
    trip = make_trip()
    if status is not TripStatus.PLANNED:
        admit(trip)
        trip.activate(requested_by=CREATOR, current_date=DAY)
    if status in (TripStatus.COMPLETED, TripStatus.ARCHIVED):
        trip.complete(
            requested_by=CREATOR, current_date=END, has_unresolved_episodes=False
        )
    if status is TripStatus.ARCHIVED:
        trip.archive(requested_by=CREATOR)
    return trip


def completion_episode(trip, completed=False):
    episode = Episode(
        EpisodeId("episode"), trip.id, CREATOR, APPLICANT, "Title", "Description", DAY
    )
    if completed:
        episode.submit(requested_by=CREATOR, trip_status=trip.status)
        episode.cast_vote(
            VoteId("vote"),
            CREATOR,
            VoteValue(4),
            eligible_voters={CREATOR},
            trip_status=trip.status,
        )
    return episode


@pytest.mark.parametrize("contents", ["empty", "completed", "foreign"])
def test_complete_queries_correct_trip_and_persists(contents: str) -> None:
    trip = lifecycle_trip()
    episode = completion_episode(
        make_trip("foreign") if contents == "foreign" else trip, contents == "completed"
    )
    episodes = CompletionEpisodes([] if contents == "empty" else [episode])
    trips = MemoryTrips([trip, make_trip("unrelated")])
    port: EpisodeRepository = episodes
    before = deepcopy([vars(e) for e in episodes.stored])
    result = CompleteTrip(trips, port).execute(
        trip_id=trip.id, requested_by=CREATOR, current_date=END
    )
    assert result.status is TripStatus.COMPLETED
    assert vars(trips.stored[trip.id]) == vars(result)
    assert trips.stored[TripId("unrelated")].status is TripStatus.PLANNED
    assert trips.saved == [trip.id]
    assert episodes.queries == [trip.id]
    assert [vars(e) for e in episodes.stored] == before


@pytest.mark.parametrize(
    "status", [EpisodeStatus.DRAFT, EpisodeStatus.SUBMITTED, EpisodeStatus.VOTING]
)
def test_unresolved_episodes_block_completion(status, monkeypatch):
    trip = lifecycle_trip()
    episode = completion_episode(trip)
    if status is EpisodeStatus.VOTING:
        episode.submit(requested_by=CREATOR, trip_status=trip.status)
    elif status is EpisodeStatus.SUBMITTED:
        # Existing loaded-state fixture pattern: SUBMITTED is transient.
        monkeypatch.setattr(episode, "_status", status)
    episodes = CompletionEpisodes([episode])
    trips = MemoryTrips([trip])
    before = deepcopy(vars(episode))
    with pytest.raises(ValueError):
        CompleteTrip(trips, episodes).execute(
            trip_id=trip.id, requested_by=CREATOR, current_date=END
        )
    assert trips.saved == []
    assert vars(trips.stored[trip.id]) == vars(trip)
    assert vars(episode) == before


def test_archive_persists_without_episode_dependency():
    trip = lifecycle_trip(TripStatus.COMPLETED)
    trips = MemoryTrips([trip])
    result = ArchiveTrip(trips).execute(trip_id=trip.id, requested_by=CREATOR)
    assert result.status is TripStatus.ARCHIVED
    assert vars(trips.stored[trip.id]) == vars(result)
    assert trips.saved == [trip.id]
    assert result.participants == trip.participants


@pytest.mark.parametrize(
    "archive,invalid",
    [
        (False, "missing"),
        (False, "actor"),
        (False, "state"),
        (False, "date"),
        (True, "missing"),
        (True, "actor"),
        (True, "state"),
    ],
)
def test_lifecycle_use_case_failures_do_not_save(archive, invalid):
    trip = lifecycle_trip(
        TripStatus.PLANNED
        if invalid == "state"
        else TripStatus.COMPLETED
        if archive
        else TripStatus.ACTIVE
    )
    trips = MemoryTrips([] if invalid == "missing" else [trip])
    episodes = CompletionEpisodes()
    args = dict(
        trip_id=trip.id, requested_by=APPLICANT if invalid == "actor" else CREATOR
    )
    with pytest.raises(LookupError if invalid == "missing" else ValueError):
        if archive:
            ArchiveTrip(trips).execute(**args)
        else:
            CompleteTrip(trips, episodes).execute(
                **args, current_date=DAY if invalid == "date" else END
            )
    assert trips.saved == []
    if invalid == "missing":
        assert episodes.queries == []
    else:
        assert vars(trips.stored[trip.id]) == vars(trip)


@pytest.mark.parametrize(
    "operation,dependency",
    [
        ("complete", "load"),
        ("complete", "query"),
        ("complete", "save"),
        ("archive", "load"),
        ("archive", "save"),
    ],
)
def test_lifecycle_repository_errors_propagate(operation, dependency, monkeypatch):
    trip = lifecycle_trip(
        TripStatus.COMPLETED if operation == "archive" else TripStatus.ACTIVE
    )
    trips = MemoryTrips([trip])
    episodes = CompletionEpisodes()
    failure = RuntimeError("Storage unavailable")

    def fail(*args, **kwargs):
        raise failure

    target = episodes if dependency == "query" else trips
    method = {"load": "get_by_id", "query": "find_unresolved_by_trip", "save": "save"}[
        dependency
    ]
    monkeypatch.setattr(target, method, fail)
    with pytest.raises(RuntimeError) as caught:
        if operation == "archive":
            ArchiveTrip(trips).execute(trip_id=trip.id, requested_by=CREATOR)
        else:
            CompleteTrip(trips, episodes).execute(
                trip_id=trip.id, requested_by=CREATOR, current_date=END
            )
    assert caught.value is failure
    assert trips.saved == []
    assert vars(trips.stored[trip.id]) == vars(trip)
