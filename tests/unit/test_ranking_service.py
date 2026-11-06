from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from itertools import permutations

import pytest

from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.services import RankingEntry, RankingService
from sillycation.domain.trip import Trip
from sillycation.domain.value_objects import InvitationCode, TripPeriod, VoteValue


DAY = date(2026, 11, 4)


def make_trip():
    trip = Trip(
        TripId("trip"),
        "Holiday",
        UserId("a"),
        TripPeriod(DAY, DAY),
        InvitationCode("code"),
    )
    for name in ("d", "c", "b"):
        request = trip.request_to_join(JoinRequestId(name), UserId(name))
        trip.approve_join_request(request.id, requested_by=trip.creator_id)
    trip.activate(requested_by=trip.creator_id, current_date=DAY)
    return trip


def make_episode(trip, name, protagonist, values=(4, 4, 4)):
    episode = Episode(
        EpisodeId(name),
        trip.id,
        UserId("a"),
        UserId(protagonist),
        "Title",
        "Description",
        DAY,
    )
    if values is not None:
        episode.submit(requested_by=episode.author_id, trip_status=trip.status)
        voters = sorted(
            (
                p.user_id
                for p in trip.participants
                if p.user_id != episode.protagonist_id
            ),
            key=lambda user: user.value,
        )
        for voter, value in zip(voters, values):
            episode.cast_vote(
                VoteId(name + voter.value),
                voter,
                VoteValue(value),
                eligible_voters=voters,
                trip_status=trip.status,
            )
    return episode


def test_sum_protagonist_scores_descending_and_include_zero():
    trip = make_trip()
    episodes = [
        make_episode(trip, "one", "b", (1, 2, 3)),
        make_episode(trip, "two", "b", (4, 4, 4)),
        make_episode(trip, "three", "c", (5, 5, 5)),
    ]
    before = deepcopy([vars(trip), *(vars(e) for e in episodes)])
    result = RankingService().calculate(trip, episodes)
    assert result == (
        RankingEntry(UserId("b"), Decimal(6), 1),
        RankingEntry(UserId("c"), Decimal(5), 2),
        RankingEntry(UserId("a"), Decimal(0), 3),
        RankingEntry(UserId("d"), Decimal(0), 3),
    )
    assert [vars(trip), *(vars(e) for e in episodes)] == before
    with pytest.raises(FrozenInstanceError):
        setattr(result[0], "score", Decimal(100))


@pytest.mark.parametrize(
    "scores,positions",
    [
        ((5, 3, 3, 1), (1, 2, 2, 4)),
        ((5, 5, 2, 2), (1, 1, 3, 3)),
        ((3, 3, 3, 1), (1, 1, 1, 4)),
    ],
)
def test_ties_and_input_order(scores, positions):
    trip = make_trip()
    episodes = [
        make_episode(trip, name, name, (score,) * 3)
        for name, score in zip("abcd", scores)
    ]
    expected = tuple(
        RankingEntry(UserId(name), Decimal(score), position)
        for name, score, position in zip("abcd", scores, positions)
    )
    for order in permutations(episodes):
        assert RankingService().calculate(trip, iter(order)) == expected


def test_decimal_scores_are_not_rounded():
    trip = make_trip()
    episodes = [
        make_episode(trip, "one", "b", (1, 1, 2)),
        make_episode(trip, "two", "b", (2, 2, 3)),
    ]
    assert RankingService().calculate(trip, episodes)[0].score == Decimal(4) / Decimal(
        3
    ) + Decimal(7) / Decimal(3)


@pytest.mark.parametrize("with_draft", [False, True])
def test_no_completed_episodes_means_all_zero_first_place(with_draft):
    trip = make_trip()
    episodes = [make_episode(trip, "draft", "b", None)] if with_draft else []
    assert RankingService().calculate(trip, episodes) == tuple(
        RankingEntry(UserId(name), Decimal(0), 1) for name in "abcd"
    )


@pytest.mark.parametrize(
    "status", [EpisodeStatus.DRAFT, EpisodeStatus.SUBMITTED, EpisodeStatus.VOTING]
)
def test_non_completed_inconsistent_episodes_are_ignored(status, monkeypatch):
    trip = make_trip()
    episode = make_episode(trip, "unresolved", "outsider", None)
    # SUBMITTED is transient: reconstruct this read-side state explicitly.
    monkeypatch.setattr(episode, "_status", status)
    assert all(
        entry.score == 0 for entry in RankingService().calculate(trip, [episode])
    )


def test_foreign_completed_inconsistent_episode_is_ignored(monkeypatch):
    trip = make_trip()
    episode = make_episode(trip, "foreign", "outsider", (4,) * 4)
    monkeypatch.setattr(episode, "_trip_id", TripId("other"))
    monkeypatch.setattr(episode, "_score", None)
    assert all(
        entry.score == 0 for entry in RankingService().calculate(trip, [episode])
    )


@pytest.mark.parametrize("missing_score", [True, False])
def test_inconsistent_completed_episode_is_rejected_without_mutation(
    missing_score, monkeypatch
):
    trip = make_trip()
    episode = make_episode(
        trip,
        "broken",
        "b" if missing_score else "outsider",
        (4,) * (3 if missing_score else 4),
    )
    if missing_score:
        monkeypatch.setattr(episode, "_score", None)
    before = deepcopy([vars(trip), vars(episode)])
    with pytest.raises(ValueError, match="score|protagonist"):
        RankingService().calculate(trip, [episode])
    assert [vars(trip), vars(episode)] == before
