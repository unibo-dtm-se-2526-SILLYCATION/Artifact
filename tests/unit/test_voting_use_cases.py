from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

import pytest

from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.application.voting_use_cases import CastVote
from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.trip import Trip, TripStatus
from sillycation.domain.value_objects import InvitationCode, TripPeriod, VoteValue


AUTHOR = UserId("author")
PROTAGONIST = UserId("protagonist")
OTHER = UserId("other")
PENDING = UserId("pending")
DAY = date(2026, 11, 3)


class MemoryTrips:
    def __init__(self, trip: Trip) -> None:
        self.stored = {trip.id: deepcopy(trip)}
        self.lookups: list[TripId] = []

    def get_by_id(self, trip_id: TripId) -> Optional[Trip]:
        self.lookups.append(trip_id)
        return deepcopy(self.stored.get(trip_id))

    def save(self, trip: Trip) -> Trip:
        raise AssertionError("Voting must not save Trip")

    def get_by_invitation_code(self, invitation_code: InvitationCode) -> Optional[Trip]:
        raise AssertionError("Unexpected invitation lookup")

    def find_by_participant(self, user_id: UserId) -> Sequence[Trip]:
        raise AssertionError("Unexpected participant query")

    def find_active_or_planned_trips_by_participant(
        self, user_id: UserId
    ) -> Sequence[Trip]:
        raise AssertionError("Unexpected conflict query")


class MemoryEpisodes:
    def __init__(self, episode: Episode) -> None:
        self.stored = {episode.id: deepcopy(episode)}
        self.saved: list[EpisodeId] = []
        self.lookups: list[EpisodeId] = []

    def get_by_id(self, episode_id: EpisodeId) -> Optional[Episode]:
        self.lookups.append(episode_id)
        return deepcopy(self.stored.get(episode_id))

    def save(self, episode: Episode) -> Episode:
        self.stored[episode.id] = deepcopy(episode)
        self.saved.append(episode.id)
        return deepcopy(episode)

    def find_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        raise AssertionError("Unexpected episode query")

    def find_unresolved_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        raise AssertionError("Unexpected unresolved query")


def make_trip(*, extra=True, active=True):
    trip = Trip(
        TripId("owning-trip"),
        "Holiday",
        AUTHOR,
        TripPeriod(DAY, DAY),
        InvitationCode("invite"),
    )
    for user in [PROTAGONIST, OTHER] if extra else [PROTAGONIST]:
        request = trip.request_to_join(JoinRequestId(user.value), user)
        trip.approve_join_request(request.id, requested_by=AUTHOR)
    trip.request_to_join(JoinRequestId("pending"), PENDING)
    if active:
        trip.activate(requested_by=AUTHOR, current_date=DAY)
    return trip


def make_episode(trip, *, submitted=True):
    episode = Episode(
        EpisodeId("episode"),
        trip.id,
        AUTHOR,
        PROTAGONIST,
        "Wrong train",
        "We took the wrong train",
        DAY,
    )
    if submitted:
        episode.submit(requested_by=AUTHOR, trip_status=TripStatus.ACTIVE)
    return episode


@pytest.fixture
def trip():
    return make_trip()


@pytest.fixture
def episode(trip):
    return make_episode(trip)


@pytest.fixture
def trips(trip):
    return MemoryTrips(trip)


@pytest.fixture
def episodes(episode):
    return MemoryEpisodes(episode)


@pytest.fixture
def data(episode):
    return dict(
        episode_id=episode.id, vote_id=VoteId("vote-1"), voter_id=AUTHOR, value=4
    )


def test_vote_is_persisted_using_ports() -> None:
    trip = make_trip()
    episode = make_episode(trip)
    trips = MemoryTrips(trip)
    episodes = MemoryEpisodes(episode)
    trip_port: TripRepository = trips
    episode_port: EpisodeRepository = episodes
    before = deepcopy(vars(trips.stored[trip.id]))
    result = CastVote(trip_port, episode_port).execute(
        episode_id=episode.id, vote_id=VoteId("vote"), voter_id=AUTHOR, value=4
    )
    (vote,) = result.votes
    assert (vote.id, vote.episode_id, vote.voter_id, vote.value) == (
        VoteId("vote"),
        episode.id,
        AUTHOR,
        VoteValue(4),
    )
    assert result.status is EpisodeStatus.VOTING
    assert result.score is None
    assert vars(episodes.stored[episode.id]) == vars(result)
    assert episodes.saved == [episode.id]
    assert trips.lookups == [episode.trip_id]
    assert vars(trips.stored[trip.id]) == before


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5])
def test_valid_values_are_persisted(trips, episodes, data, value):
    result = CastVote(trips, episodes).execute(**{**data, "value": value})
    assert episodes.stored[result.id].votes[0].value == VoteValue(value)


@pytest.mark.parametrize("voter", [PROTAGONIST, UserId("outsider"), PENDING])
def test_ineligible_voter_rejected_without_save(trips, episodes, episode, data, voter):
    with pytest.raises(ValueError):
        CastVote(trips, episodes).execute(**{**data, "voter_id": voter})
    assert episodes.saved == []
    assert vars(episodes.stored[episode.id]) == vars(episode)


@pytest.mark.parametrize("value", [0, 6, 2.5, 4.0, True, False, "4"])
def test_invalid_values_are_not_coerced(trips, episodes, episode, data, value):
    with pytest.raises(ValueError, match="integer"):
        CastVote(trips, episodes).execute(**{**data, "value": value})
    assert episodes.saved == []
    assert vars(episodes.stored[episode.id]) == vars(episode)


def test_reloaded_votes_use_all_members_and_complete_with_decimal_score(
    trips, episodes, data
):
    use_case = CastVote(trips, episodes)
    first = use_case.execute(**{**data, "value": 2})
    # OTHER must also vote; the pending applicant and protagonist must not.
    assert first.status is EpisodeStatus.VOTING
    assert first.score is None
    last = use_case.execute(
        **{**data, "vote_id": VoteId("vote-2"), "voter_id": OTHER, "value": 5}
    )
    assert last.status is EpisodeStatus.COMPLETED
    assert last.score == Decimal("3.5")
    assert isinstance(last.score, Decimal)
    assert {v.voter_id for v in last.votes} == {AUTHOR, OTHER}
    assert vars(episodes.stored[last.id]) == vars(last)
    assert episodes.lookups == [last.id, last.id]
    assert episodes.saved == [last.id, last.id]
    assert len(first.votes) == 1


def test_two_participants_complete_on_first_eligible_vote():
    trip = make_trip(extra=False)
    episode = make_episode(trip)
    trips = MemoryTrips(trip)
    episodes = MemoryEpisodes(episode)
    result = CastVote(trips, episodes).execute(
        episode_id=episode.id, vote_id=VoteId("only"), voter_id=AUTHOR, value=3
    )
    assert result.status is EpisodeStatus.COMPLETED
    assert result.score == Decimal(3)
    assert vars(episodes.stored[result.id]) == vars(result)


@pytest.mark.parametrize("duplicate", ["voter", "vote_id"])
def test_duplicates_do_not_replace_persisted_vote(trips, episodes, data, duplicate):
    use_case = CastVote(trips, episodes)
    first = use_case.execute(**data)
    episodes.saved.clear()
    changes = (
        {"vote_id": VoteId("new")} if duplicate == "voter" else {"voter_id": OTHER}
    )
    with pytest.raises(ValueError):
        use_case.execute(**{**data, **changes, "value": 1})
    assert episodes.saved == []
    assert vars(episodes.stored[first.id]) == vars(first)


def test_completed_episode_rejects_further_votes(trips, episodes, data):
    use_case = CastVote(trips, episodes)
    use_case.execute(**data)
    completed = use_case.execute(
        **{**data, "vote_id": VoteId("last"), "voter_id": OTHER}
    )
    episodes.saved.clear()
    with pytest.raises(ValueError, match="VOTING"):
        use_case.execute(**{**data, "vote_id": VoteId("late")})
    assert episodes.saved == []
    assert vars(episodes.stored[completed.id]) == vars(completed)


def test_draft_episode_rejects_vote(trip, trips, data):
    draft = make_episode(trip, submitted=False)
    episodes = MemoryEpisodes(draft)
    with pytest.raises(ValueError, match="VOTING"):
        CastVote(trips, episodes).execute(**data)
    assert episodes.saved == []
    assert vars(episodes.stored[draft.id]) == vars(draft)


def test_non_active_owning_trip_rejects_vote(episodes, episode, data):
    planned = make_trip(active=False)
    trips = MemoryTrips(planned)
    # A different ACTIVE Trip must not be used as the voting context.
    other = Trip(
        TripId("other-trip"),
        "Other",
        AUTHOR,
        TripPeriod(DAY, DAY),
        InvitationCode("other"),
    )
    request = other.request_to_join(JoinRequestId("other-join"), PROTAGONIST)
    other.approve_join_request(request.id, requested_by=AUTHOR)
    other.activate(requested_by=AUTHOR, current_date=DAY)
    trips.stored[other.id] = other
    with pytest.raises(ValueError, match="ACTIVE"):
        CastVote(trips, episodes).execute(**data)
    assert trips.lookups == [episode.trip_id]
    assert episodes.saved == []
    assert vars(episodes.stored[episode.id]) == vars(episode)


@pytest.mark.parametrize("missing", ["Episode", "Trip"])
def test_missing_aggregate_is_explicit(trips, episodes, data, missing):
    (episodes if missing == "Episode" else trips).stored.clear()
    with pytest.raises(LookupError, match=missing):
        CastVote(trips, episodes).execute(**data)
    assert episodes.saved == []
    if missing == "Episode":
        assert trips.lookups == []


@pytest.mark.parametrize("dependency", ["episode_lookup", "trip_lookup", "save"])
def test_repository_errors_propagate_without_persisting(
    trips, episodes, episode, data, dependency, monkeypatch
):
    failure = RuntimeError("Repository unavailable")

    def fail(*args):
        raise failure

    target = trips if dependency == "trip_lookup" else episodes
    monkeypatch.setattr(target, "save" if dependency == "save" else "get_by_id", fail)
    with pytest.raises(RuntimeError) as error:
        CastVote(trips, episodes).execute(**data)
    assert error.value is failure
    assert episodes.saved == []
    assert vars(episodes.stored[episode.id]) == vars(episode)
