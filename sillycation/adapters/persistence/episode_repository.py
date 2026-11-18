"""EpisodeRepository backed by a relational database."""

from typing import Optional, Sequence

from sqlalchemy import ColumnElement, Engine, delete, insert, select

from sillycation.adapters.persistence.tables import episodes, votes
from sillycation.domain.episode import Episode, EpisodeStatus, Vote
from sillycation.domain.errors import NotFound
from sillycation.domain.identifiers import EpisodeId, TripId, UserId, VoteId
from sillycation.domain.value_objects import VoteValue

UNRESOLVED_STATUSES = [
    EpisodeStatus.DRAFT.value,
    EpisodeStatus.SUBMITTED.value,
    EpisodeStatus.VOTING.value,
]


class SqlAlchemyEpisodeRepository:
    """Implements the EpisodeRepository port.

    An Episode is stored and loaded as a whole, together with its votes. Saving
    replaces every stored row of that Episode inside one transaction. The score
    is not stored: Episode.restore recomputes it from the votes.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, episode: Episode) -> Episode:
        episode_id = episode.id.value
        with self._engine.begin() as connection:
            connection.execute(delete(votes).where(votes.c.episode_id == episode_id))
            connection.execute(delete(episodes).where(episodes.c.id == episode_id))
            connection.execute(
                insert(episodes).values(
                    id=episode_id,
                    trip_id=episode.trip_id.value,
                    author_id=episode.author_id.value,
                    protagonist_id=episode.protagonist_id.value,
                    title=episode.title,
                    description=episode.description,
                    date=episode.date,
                    status=episode.status.value,
                )
            )
            if episode.votes:
                connection.execute(
                    insert(votes),
                    [
                        {
                            "id": vote.id.value,
                            "episode_id": episode_id,
                            "voter_id": vote.voter_id.value,
                            "value": vote.value.value,
                        }
                        for vote in episode.votes
                    ],
                )
        return episode

    def delete(self, episode_id: EpisodeId) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                delete(votes).where(votes.c.episode_id == episode_id.value)
            )
            deleted = connection.execute(
                delete(episodes).where(episodes.c.id == episode_id.value)
            )
            if deleted.rowcount == 0:
                raise NotFound("Episode not found")

    def get_by_id(self, episode_id: EpisodeId) -> Optional[Episode]:
        found = self._load(episodes.c.id == episode_id.value)
        return found[0] if found else None

    def find_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        return self._load(episodes.c.trip_id == trip_id.value)

    def find_unresolved_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        return self._load(
            (episodes.c.trip_id == trip_id.value)
            & episodes.c.status.in_(UNRESOLVED_STATUSES)
        )

    def _load(self, condition: ColumnElement[bool]) -> list[Episode]:
        """Read the matching episodes with two queries, whatever their number."""
        with self._engine.connect() as connection:
            episode_rows = connection.execute(
                select(episodes).where(condition).order_by(episodes.c.id)
            ).all()
            episode_ids = [row.id for row in episode_rows]
            vote_rows = connection.execute(
                select(votes)
                .where(votes.c.episode_id.in_(episode_ids))
                .order_by(votes.c.id)
            ).all()
        return [
            Episode.restore(
                id=EpisodeId(row.id),
                trip_id=TripId(row.trip_id),
                author_id=UserId(row.author_id),
                protagonist_id=UserId(row.protagonist_id),
                title=row.title,
                description=row.description,
                date=row.date,
                status=EpisodeStatus(row.status),
                votes=[
                    Vote(
                        VoteId(vote.id),
                        EpisodeId(vote.episode_id),
                        UserId(vote.voter_id),
                        VoteValue(vote.value),
                    )
                    for vote in vote_rows
                    if vote.episode_id == row.id
                ],
            )
            for row in episode_rows
        ]
