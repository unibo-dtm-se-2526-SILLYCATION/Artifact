"""TripRepository backed by a relational database."""

from typing import Optional, Sequence

from sqlalchemy import ColumnElement, Engine, delete, insert, select, update

from sillycation.adapters.persistence.tables import join_requests, participants, trips
from sillycation.domain.identifiers import JoinRequestId, TripId, UserId
from sillycation.domain.trip import JoinRequest, JoinRequestStatus, Trip, TripStatus
from sillycation.domain.value_objects import InvitationCode, TripPeriod


class SqlAlchemyTripRepository:
    """Implements the TripRepository port.

    A Trip is stored and loaded as a whole, together with its participants and
    join requests. Saving preserves the parent row and replaces its owned rows
    inside one transaction, so references from Episodes remain valid.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save(self, trip: Trip) -> Trip:
        trip_id = trip.id.value
        with self._engine.begin() as connection:
            values = dict(
                name=trip.name,
                description=trip.description,
                creator_id=trip.creator_id.value,
                start_date=trip.period.start_date,
                end_date=trip.period.end_date,
                invitation_code=trip.invitation_code.value,
                status=trip.status.value,
            )
            exists = connection.execute(
                select(trips.c.id).where(trips.c.id == trip_id)
            ).first()
            if exists is None:
                connection.execute(insert(trips).values(id=trip_id, **values))
            else:
                connection.execute(
                    update(trips).where(trips.c.id == trip_id).values(**values)
                )
            connection.execute(
                delete(participants).where(participants.c.trip_id == trip_id)
            )
            connection.execute(
                delete(join_requests).where(join_requests.c.trip_id == trip_id)
            )
            connection.execute(
                insert(participants),
                [
                    {"trip_id": trip_id, "user_id": participant.user_id.value}
                    for participant in trip.participants
                ],
            )
            if trip.join_requests:
                connection.execute(
                    insert(join_requests),
                    [
                        {
                            "id": request.id.value,
                            "trip_id": trip_id,
                            "user_id": request.user_id.value,
                            "status": request.status.value,
                        }
                        for request in trip.join_requests
                    ],
                )
        return trip

    def get_by_id(self, trip_id: TripId) -> Optional[Trip]:
        found = self._load(trips.c.id == trip_id.value)
        return found[0] if found else None

    def get_by_invitation_code(self, invitation_code: InvitationCode) -> Optional[Trip]:
        found = self._load(trips.c.invitation_code == invitation_code.value)
        return found[0] if found else None

    def find_by_participant(self, user_id: UserId) -> Sequence[Trip]:
        return self._load(self._has_participant(user_id))

    def find_active_or_planned_trips_by_participant(
        self, user_id: UserId
    ) -> Sequence[Trip]:
        open_statuses = [TripStatus.PLANNED.value, TripStatus.ACTIVE.value]
        return self._load(
            self._has_participant(user_id) & trips.c.status.in_(open_statuses)
        )

    @staticmethod
    def _has_participant(user_id: UserId) -> ColumnElement[bool]:
        memberships = select(participants.c.trip_id).where(
            participants.c.user_id == user_id.value
        )
        return trips.c.id.in_(memberships)

    def _load(self, condition: ColumnElement[bool]) -> list[Trip]:
        """Read the matching trips with three queries, whatever their number."""
        with self._engine.connect() as connection:
            trip_rows = connection.execute(
                select(trips).where(condition).order_by(trips.c.id)
            ).all()
            trip_ids = [row.id for row in trip_rows]
            participant_rows = connection.execute(
                select(participants).where(participants.c.trip_id.in_(trip_ids))
            ).all()
            request_rows = connection.execute(
                select(join_requests)
                .where(join_requests.c.trip_id.in_(trip_ids))
                .order_by(join_requests.c.id)
            ).all()
        return [
            Trip.restore(
                id=TripId(row.id),
                name=row.name,
                creator_id=UserId(row.creator_id),
                period=TripPeriod(row.start_date, row.end_date),
                invitation_code=InvitationCode(row.invitation_code),
                description=row.description,
                status=TripStatus(row.status),
                participants=[
                    UserId(member.user_id)
                    for member in participant_rows
                    if member.trip_id == row.id
                ],
                join_requests=[
                    JoinRequest(
                        JoinRequestId(request.id),
                        TripId(request.trip_id),
                        UserId(request.user_id),
                        JoinRequestStatus(request.status),
                    )
                    for request in request_rows
                    if request.trip_id == row.id
                ],
            )
            for row in trip_rows
        ]
