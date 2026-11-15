"""Rebuilding aggregates from stored state, as a repository would."""

from datetime import date
from decimal import Decimal

import pytest

from sillycation.domain.episode import Episode, EpisodeStatus, Vote
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.trip import (
    JoinRequest,
    JoinRequestStatus,
    Participant,
    Trip,
    TripStatus,
)
from sillycation.domain.value_objects import InvitationCode, TripPeriod, VoteValue


TRIP = TripId("trip")
EPISODE = EpisodeId("episode")
CREATOR = UserId("creator")
MEMBER = UserId("member")
OTHER = UserId("other")
START = date(2026, 11, 10)
END = date(2026, 11, 12)


def restore_trip(
    status=TripStatus.PLANNED, participants=(CREATOR, MEMBER), join_requests=()
):
    return Trip.restore(
        id=TRIP,
        name="Lisbon",
        creator_id=CREATOR,
        period=TripPeriod(START, END),
        invitation_code=InvitationCode("CODE"),
        description="Autumn break",
        status=status,
        participants=participants,
        join_requests=join_requests,
    )


def restore_episode(status=EpisodeStatus.DRAFT, votes=()):
    return Episode.restore(
        id=EPISODE,
        trip_id=TRIP,
        author_id=CREATOR,
        protagonist_id=MEMBER,
        title="Lost passport",
        description="Left it at the hotel",
        date=START,
        status=status,
        votes=votes,
    )


def vote(voter, value, key="vote", episode=EPISODE):
    return Vote(VoteId(f"{key}-{voter.value}"), episode, voter, VoteValue(value))


@pytest.mark.parametrize("status", list(TripStatus))
def test_trip_is_restored_in_every_status(status: TripStatus) -> None:
    trip = restore_trip(status)

    assert trip.status is status
    assert trip.id == TRIP
    assert trip.name == "Lisbon"
    assert trip.creator_id == CREATOR
    assert trip.period == TripPeriod(START, END)
    assert trip.invitation_code == InvitationCode("CODE")
    assert trip.description == "Autumn break"
    assert trip.participants == {Participant(TRIP, CREATOR), Participant(TRIP, MEMBER)}


def test_trip_is_restored_with_its_join_requests() -> None:
    pending = JoinRequest(JoinRequestId("r1"), TRIP, OTHER)
    approved = JoinRequest(
        JoinRequestId("r2"), TRIP, MEMBER, JoinRequestStatus.APPROVED
    )

    trip = restore_trip(join_requests=[pending, approved])

    assert set(trip.join_requests) == {pending, approved}
    assert trip.get_join_request(JoinRequestId("r1")) == pending


def test_restored_planned_trip_keeps_working() -> None:
    pending = JoinRequest(JoinRequestId("r1"), TRIP, OTHER)
    trip = restore_trip(join_requests=[pending])

    trip.approve_join_request(JoinRequestId("r1"), requested_by=CREATOR)
    trip.activate(requested_by=CREATOR, current_date=START)

    assert Participant(TRIP, OTHER) in trip.participants
    assert trip.status is TripStatus.ACTIVE


def test_restored_active_trip_rejects_new_join_requests() -> None:
    trip = restore_trip(TripStatus.ACTIVE)

    with pytest.raises(ValueError):
        trip.request_to_join(JoinRequestId("r1"), OTHER)


def test_restored_completed_trip_can_be_archived() -> None:
    trip = restore_trip(TripStatus.COMPLETED)

    trip.archive(requested_by=CREATOR)

    assert trip.status is TripStatus.ARCHIVED


def test_trip_restore_requires_creator_among_participants() -> None:
    with pytest.raises(ValueError):
        restore_trip(participants=[MEMBER])


def test_trip_restore_rejects_foreign_join_requests() -> None:
    foreign = JoinRequest(JoinRequestId("r1"), TripId("another"), OTHER)

    with pytest.raises(ValueError):
        restore_trip(join_requests=[foreign])


def test_draft_episode_is_restored() -> None:
    episode = restore_episode()

    assert episode.status is EpisodeStatus.DRAFT
    assert episode.id == EPISODE
    assert episode.trip_id == TRIP
    assert episode.author_id == CREATOR
    assert episode.protagonist_id == MEMBER
    assert episode.title == "Lost passport"
    assert episode.description == "Left it at the hotel"
    assert episode.date == START
    assert episode.votes == ()
    assert episode.score is None


def test_restored_draft_episode_can_be_submitted() -> None:
    episode = restore_episode()

    episode.submit(requested_by=CREATOR, trip_status=TripStatus.ACTIVE)

    assert episode.status is EpisodeStatus.VOTING


def test_submitted_episode_is_restored() -> None:
    episode = restore_episode(EpisodeStatus.SUBMITTED)

    assert episode.status is EpisodeStatus.SUBMITTED
    assert episode.score is None


def test_voting_episode_is_restored_with_its_votes() -> None:
    episode = restore_episode(EpisodeStatus.VOTING, [vote(CREATOR, 4)])

    assert episode.status is EpisodeStatus.VOTING
    assert episode.votes == (vote(CREATOR, 4),)
    assert episode.has_vote_from(CREATOR)
    assert episode.score is None


def test_restored_voting_episode_completes_with_the_last_vote() -> None:
    episode = restore_episode(EpisodeStatus.VOTING, [vote(CREATOR, 4)])

    episode.cast_vote(
        VoteId("last"),
        OTHER,
        VoteValue(5),
        eligible_voters={CREATOR, OTHER},
        trip_status=TripStatus.ACTIVE,
    )

    assert episode.status is EpisodeStatus.COMPLETED
    assert episode.score == Decimal("4.5")


def test_restored_voting_episode_rejects_a_second_vote_from_the_same_user() -> None:
    episode = restore_episode(EpisodeStatus.VOTING, [vote(CREATOR, 4)])

    with pytest.raises(ValueError):
        episode.cast_vote(
            VoteId("again"),
            CREATOR,
            VoteValue(2),
            eligible_voters={CREATOR, OTHER},
            trip_status=TripStatus.ACTIVE,
        )


def test_completed_episode_is_restored_with_its_score() -> None:
    episode = restore_episode(
        EpisodeStatus.COMPLETED, [vote(CREATOR, 5), vote(OTHER, 4)]
    )

    assert episode.status is EpisodeStatus.COMPLETED
    assert episode.score == Decimal("4.5")
    assert len(episode.votes) == 2


def test_restored_completed_episode_rejects_new_votes() -> None:
    episode = restore_episode(EpisodeStatus.COMPLETED, [vote(CREATOR, 5)])

    with pytest.raises(ValueError):
        episode.cast_vote(
            VoteId("late"),
            OTHER,
            VoteValue(3),
            eligible_voters={CREATOR, OTHER},
            trip_status=TripStatus.ACTIVE,
        )


def test_episode_restore_rejects_votes_on_a_draft() -> None:
    with pytest.raises(ValueError):
        restore_episode(EpisodeStatus.DRAFT, [vote(CREATOR, 4)])


def test_episode_restore_rejects_a_completed_episode_without_votes() -> None:
    with pytest.raises(ValueError):
        restore_episode(EpisodeStatus.COMPLETED)


def test_episode_restore_rejects_foreign_votes() -> None:
    foreign = vote(CREATOR, 4, episode=EpisodeId("another"))

    with pytest.raises(ValueError):
        restore_episode(EpisodeStatus.VOTING, [foreign])
