"""SqlAlchemyEpisodeRepository against a real SQLite database."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine

from sillycation.adapters.persistence.database import create_database
from sillycation.adapters.persistence.episode_repository import (
    SqlAlchemyEpisodeRepository,
)
from sillycation.application.ports.repositories import EpisodeRepository
from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.errors import NotFound
from sillycation.domain.identifiers import EpisodeId, TripId, UserId, VoteId
from sillycation.domain.trip import TripStatus
from sillycation.domain.value_objects import VoteValue


TRIP = TripId("trip")
AUTHOR = UserId("author")
PROTAGONIST = UserId("protagonist")
OTHER = UserId("other")
VOTERS = {AUTHOR, OTHER}
DAY = date(2026, 11, 10)


@pytest.fixture
def episodes(engine: Engine) -> EpisodeRepository:
    return SqlAlchemyEpisodeRepository(engine)


def cast(episode: Episode, voter: UserId, value: int) -> None:
    episode.cast_vote(
        VoteId(f"{episode.id.value}-{voter.value}"),
        voter,
        VoteValue(value),
        eligible_voters=VOTERS,
        trip_status=TripStatus.ACTIVE,
    )


def make_episode(
    key: str = "episode",
    status: EpisodeStatus = EpisodeStatus.DRAFT,
    trip_id: TripId = TRIP,
) -> Episode:
    """Build an episode moved forward to the given status through real votes."""
    episode = Episode(
        EpisodeId(key), trip_id, AUTHOR, PROTAGONIST, f"Title {key}", "Details", DAY
    )
    if status is not EpisodeStatus.DRAFT:
        episode.submit(requested_by=AUTHOR, trip_status=TripStatus.ACTIVE)
    if status is EpisodeStatus.COMPLETED:
        cast(episode, AUTHOR, 5)
        cast(episode, OTHER, 4)
    return episode


def assert_same_episode(loaded: Episode, original: Episode) -> None:
    assert loaded.id == original.id
    assert loaded.trip_id == original.trip_id
    assert loaded.author_id == original.author_id
    assert loaded.protagonist_id == original.protagonist_id
    assert loaded.title == original.title
    assert loaded.description == original.description
    assert loaded.date == original.date
    assert loaded.status is original.status
    assert set(loaded.votes) == set(original.votes)
    assert loaded.score == original.score


@pytest.mark.parametrize(
    "status", [EpisodeStatus.DRAFT, EpisodeStatus.VOTING, EpisodeStatus.COMPLETED]
)
def test_episode_is_saved_and_loaded_in_every_reachable_status(
    episodes: EpisodeRepository, status: EpisodeStatus
) -> None:
    episode = make_episode(status=status)

    assert episodes.save(episode) is episode
    loaded = episodes.get_by_id(episode.id)

    assert loaded is not None
    assert_same_episode(loaded, episode)


def test_partially_voted_episode_keeps_its_votes(episodes: EpisodeRepository) -> None:
    episode = make_episode(status=EpisodeStatus.VOTING)
    cast(episode, AUTHOR, 3)
    episodes.save(episode)

    loaded = episodes.get_by_id(episode.id)

    assert loaded is not None
    assert loaded.status is EpisodeStatus.VOTING
    assert loaded.has_vote_from(AUTHOR)
    assert not loaded.has_vote_from(OTHER)
    assert loaded.score is None


def test_loaded_episode_completes_with_the_last_vote(
    episodes: EpisodeRepository,
) -> None:
    episode = make_episode(status=EpisodeStatus.VOTING)
    cast(episode, AUTHOR, 3)
    episodes.save(episode)

    loaded = episodes.get_by_id(episode.id)
    assert loaded is not None
    cast(loaded, OTHER, 4)
    episodes.save(loaded)
    completed = episodes.get_by_id(episode.id)

    assert completed is not None
    assert completed.status is EpisodeStatus.COMPLETED
    assert completed.score == Decimal("3.5")
    assert len(completed.votes) == 2


def test_completed_episode_score_is_recomputed_from_stored_votes(
    episodes: EpisodeRepository,
) -> None:
    episodes.save(make_episode(status=EpisodeStatus.COMPLETED))

    loaded = episodes.get_by_id(EpisodeId("episode"))

    assert loaded is not None
    assert loaded.score == Decimal("4.5")


def test_saving_again_replaces_the_stored_episode(episodes: EpisodeRepository) -> None:
    episode = make_episode()
    episodes.save(episode)

    episode.edit(
        requested_by=AUTHOR,
        title="New title",
        description="New details",
        date=date(2026, 11, 11),
        protagonist_id=OTHER,
    )
    episodes.save(episode)
    loaded = episodes.get_by_id(episode.id)

    assert loaded is not None
    assert_same_episode(loaded, episode)
    assert loaded.title == "New title"
    assert loaded.protagonist_id == OTHER


def test_unknown_episode_is_not_found(episodes: EpisodeRepository) -> None:
    assert episodes.get_by_id(EpisodeId("missing")) is None


def test_deleted_episode_is_no_longer_found(episodes: EpisodeRepository) -> None:
    episodes.save(make_episode("kept"))
    episodes.save(make_episode("removed"))

    episodes.delete(EpisodeId("removed"))

    assert episodes.get_by_id(EpisodeId("removed")) is None
    assert episodes.get_by_id(EpisodeId("kept")) is not None


def test_deleting_an_unknown_episode_raises_not_found(
    episodes: EpisodeRepository,
) -> None:
    with pytest.raises(NotFound):
        episodes.delete(EpisodeId("missing"))


def test_find_by_trip_returns_only_that_trips_episodes_in_any_status(
    episodes: EpisodeRepository,
) -> None:
    episodes.save(make_episode("draft", EpisodeStatus.DRAFT))
    episodes.save(make_episode("voting", EpisodeStatus.VOTING))
    episodes.save(make_episode("completed", EpisodeStatus.COMPLETED))
    episodes.save(make_episode("foreign", trip_id=TripId("another")))

    found = episodes.find_by_trip(TRIP)

    assert {episode.id.value for episode in found} == {"draft", "voting", "completed"}
    completed = next(e for e in found if e.id == EpisodeId("completed"))
    assert len(completed.votes) == 2
    assert episodes.find_by_trip(TripId("empty")) == []


def test_find_unresolved_by_trip_excludes_completed_episodes(
    episodes: EpisodeRepository,
) -> None:
    episodes.save(make_episode("draft", EpisodeStatus.DRAFT))
    episodes.save(make_episode("voting", EpisodeStatus.VOTING))
    episodes.save(make_episode("completed", EpisodeStatus.COMPLETED))
    episodes.save(make_episode("foreign", trip_id=TripId("another")))

    found = episodes.find_unresolved_by_trip(TRIP)

    assert {episode.id.value for episode in found} == {"draft", "voting"}


def test_episodes_survive_an_application_restart(database_url: str) -> None:
    episode = make_episode(status=EpisodeStatus.COMPLETED)
    first_run = create_database(database_url)
    SqlAlchemyEpisodeRepository(first_run).save(episode)
    first_run.dispose()

    second_run = create_database(database_url)
    loaded = SqlAlchemyEpisodeRepository(second_run).get_by_id(episode.id)
    second_run.dispose()

    assert loaded is not None
    assert_same_episode(loaded, episode)
