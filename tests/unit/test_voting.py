from datetime import date
from decimal import Decimal

import pytest

from sillycation.domain.episode import Episode, EpisodeStatus, Vote
from sillycation.domain.identifiers import EpisodeId, TripId, UserId, VoteId
from sillycation.domain.trip import TripStatus
from sillycation.domain.value_objects import VoteValue


AUTHOR = UserId("author")
PROTAGONIST = UserId("protagonist")
OTHER = UserId("other")
ELIGIBLE = {AUTHOR, OTHER}


@pytest.fixture
def draft():
    return Episode(
        EpisodeId("episode"),
        TripId("trip"),
        AUTHOR,
        PROTAGONIST,
        "Wrong train",
        "We boarded the wrong train",
        date(2026, 10, 25),
    )


@pytest.fixture
def episode(draft):
    draft.submit(requested_by=AUTHOR, trip_status=TripStatus.ACTIVE)
    return draft


def cast(
    episode,
    voter=AUTHOR,
    value=4,
    vote_id="vote-1",
    eligible=None,
    status=TripStatus.ACTIVE,
):
    return episode.cast_vote(
        VoteId(vote_id),
        voter,
        VoteValue(value),
        eligible_voters=ELIGIBLE if eligible is None else eligible,
        trip_status=status,
    )


def test_vote_records_identity_and_validated_value(episode):
    vote = cast(episode)
    assert isinstance(vote, Vote)
    assert vote.id == VoteId("vote-1")
    assert vote.episode_id == episode.id
    assert vote.voter_id == AUTHOR
    assert vote.value == VoteValue(4)
    assert episode.votes == (vote,)
    assert episode.has_vote_from(AUTHOR)
    assert not episode.has_vote_from(OTHER)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", VoteId("other")),
        ("episode_id", EpisodeId("other")),
        ("voter_id", OTHER),
        ("value", VoteValue(1)),
    ],
)
def test_registered_vote_is_immutable(episode, field, value):
    vote = cast(episode)
    with pytest.raises(AttributeError):
        setattr(vote, field, value)
    assert episode.votes[0].value == VoteValue(4)


def test_vote_requires_validated_vote_value(episode):
    with pytest.raises(ValueError):
        episode.cast_vote(
            VoteId("raw"),
            AUTHOR,
            4,
            eligible_voters=ELIGIBLE,
            trip_status=TripStatus.ACTIVE,
        )
    assert episode.votes == ()
    assert episode.score is None


def test_draft_cannot_receive_votes(draft):
    with pytest.raises(ValueError):
        cast(draft)
    assert draft.votes == ()
    assert draft.score is None
    assert draft.status is EpisodeStatus.DRAFT


@pytest.mark.parametrize(
    "status", [TripStatus.PLANNED, TripStatus.COMPLETED, TripStatus.ARCHIVED]
)
def test_voting_requires_active_trip(episode, status):
    with pytest.raises(ValueError):
        cast(episode, status=status)
    assert episode.votes == ()
    assert episode.status is EpisodeStatus.VOTING


@pytest.mark.parametrize("eligible", [ELIGIBLE, ELIGIBLE | {PROTAGONIST}])
def test_protagonist_cannot_vote_even_if_supplied_as_eligible(episode, eligible):
    with pytest.raises(ValueError):
        cast(episode, voter=PROTAGONIST, eligible=eligible)
    assert episode.votes == ()


def test_noneligible_user_cannot_vote(episode):
    with pytest.raises(ValueError):
        cast(episode, voter=UserId("outsider"))
    assert episode.votes == ()


def test_duplicate_voter_is_rejected_without_replacing_vote(episode):
    first = cast(episode)
    with pytest.raises(ValueError):
        cast(episode, vote_id="new-id", value=1)
    assert episode.votes == (first,)
    assert episode.score is None


def test_vote_id_cannot_be_reused_by_another_voter(episode):
    first = cast(episode)
    with pytest.raises(ValueError):
        cast(episode, voter=OTHER)
    assert episode.votes == (first,)
    assert not episode.has_vote_from(OTHER)


@pytest.mark.parametrize("values", [(5,), (1, 5), (5, 4, 3), (1, 1, 2)])
def test_completion_and_mean_after_last_eligible_vote(episode, values):
    voters = [UserId(str(index)) for index in range(len(values))]
    assert episode.score is None
    for index, (voter, value) in enumerate(zip(voters, values)):
        cast(episode, voter, value, str(index), set(voters))
        if index < len(values) - 1:
            assert episode.status is EpisodeStatus.VOTING
            assert episode.score is None
    assert episode.status is EpisodeStatus.COMPLETED
    assert episode.score == Decimal(sum(values)) / Decimal(len(values))
    assert isinstance(episode.score, Decimal)


def test_completed_episode_rejects_further_votes(episode):
    cast(episode, eligible={AUTHOR})
    before = episode.votes
    score = episode.score
    with pytest.raises(ValueError):
        cast(episode, voter=OTHER, vote_id="late")
    assert episode.votes == before
    assert episode.score == score
    assert episode.status is EpisodeStatus.COMPLETED


@pytest.mark.parametrize("eligible", [set(), {AUTHOR, PROTAGONIST}])
def test_invalid_eligible_context_does_not_record_vote(episode, eligible):
    with pytest.raises(ValueError):
        cast(episode, eligible=eligible)
    assert episode.votes == ()
    cast(episode)
    assert episode.status is EpisodeStatus.VOTING


@pytest.mark.parametrize("changed", [{OTHER}, ELIGIBLE | {UserId("extra")}])
def test_eligible_set_cannot_change_during_voting(episode, changed):
    cast(episode)
    with pytest.raises(ValueError):
        cast(episode, voter=OTHER, vote_id="second", eligible=changed)
    assert len(episode.votes) == 1
    assert episode.score is None
    cast(episode, voter=OTHER, vote_id="second")
    assert episode.status is EpisodeStatus.COMPLETED


def test_caller_cannot_mutate_stored_eligible_set(episode):
    supplied = set(ELIGIBLE)
    cast(episode, eligible=supplied)
    supplied.clear()
    cast(episode, voter=OTHER, vote_id="second", eligible=set(ELIGIBLE))
    assert episode.status is EpisodeStatus.COMPLETED


def test_votes_and_score_cannot_be_modified_externally(episode):
    cast(episode)
    snapshot = episode.votes
    with pytest.raises(AttributeError):
        snapshot.clear()
    with pytest.raises(AttributeError):
        episode.votes = ()
    with pytest.raises(AttributeError):
        episode.score = Decimal(5)
    cast(episode, voter=OTHER, vote_id="second")
    assert len(snapshot) == 1
    assert len(episode.votes) == 2


def test_completed_episode_cannot_be_edited_or_resubmitted(episode):
    cast(episode, eligible={AUTHOR})
    with pytest.raises(ValueError):
        episode.submit(requested_by=AUTHOR, trip_status=TripStatus.ACTIVE)
    with pytest.raises(ValueError):
        episode.edit(
            requested_by=AUTHOR,
            title="Changed",
            description="Changed",
            date=episode.date,
            protagonist_id=AUTHOR,
        )
    assert episode.status is EpisodeStatus.COMPLETED
    assert episode.title == "Wrong train"
