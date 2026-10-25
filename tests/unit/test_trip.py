from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from sillycation.domain.identifiers import JoinRequestId, TripId, UserId
from sillycation.domain.trip import Participant, Trip, TripStatus
from sillycation.domain.value_objects import InvitationCode, TripPeriod


CREATOR = UserId("creator")
GUEST = UserId("guest")
START = date(2026, 10, 10)
END = date(2026, 10, 15)


def admit(trip, user_id, *, requested_by):
    request = trip.request_to_join(JoinRequestId(user_id.value), user_id)
    trip.approve_join_request(request.id, requested_by=requested_by)


@pytest.fixture
def trip():
    return Trip(
        id=TripId("trip-1"),
        name="Autumn holiday",
        creator_id=CREATOR,
        period=TripPeriod(START, END),
        invitation_code=InvitationCode("invite-1"),
    )


def test_trip_creation_starts_planned_with_creator_as_only_participant(trip):
    assert trip.id == TripId("trip-1")
    assert trip.name == "Autumn holiday"
    assert trip.creator_id == CREATOR
    assert trip.period == TripPeriod(START, END)
    assert trip.invitation_code == InvitationCode("invite-1")
    assert trip.description is None
    assert trip.status is TripStatus.PLANNED
    assert trip.participants == frozenset({Participant(trip.id, CREATOR)})


def test_trip_can_have_description_and_single_day_period():
    trip = Trip(
        TripId("day-trip"),
        "Day trip",
        CREATOR,
        TripPeriod(START, START),
        InvitationCode("invite"),
        "A day away",
    )
    assert trip.description == "A day away"
    assert trip.period.start_date == trip.period.end_date == START


def test_invalid_dates_are_rejected_by_trip_period():
    with pytest.raises(ValueError):
        Trip(
            TripId("trip"),
            "Holiday",
            CREATOR,
            TripPeriod(END, START),
            InvitationCode("invite"),
        )


def test_participant_identity_is_user_and_trip():
    participant = Participant(TripId("trip-1"), CREATOR)
    assert participant == Participant(TripId("trip-1"), UserId("creator"))
    assert participant != Participant(TripId("trip-2"), CREATOR)
    assert participant != Participant(TripId("trip-1"), GUEST)


@pytest.mark.parametrize(
    "attribute,value", [("trip_id", TripId("other")), ("user_id", GUEST)]
)
def test_participant_identity_cannot_be_changed(attribute, value):
    participant = Participant(TripId("trip-1"), CREATOR)
    with pytest.raises(FrozenInstanceError):
        setattr(participant, attribute, value)


def test_creator_can_add_participant_while_planned(trip):
    admit(trip, GUEST, requested_by=CREATOR)
    assert trip.participants == frozenset(
        {
            Participant(trip.id, CREATOR),
            Participant(trip.id, GUEST),
        }
    )
    assert trip.status is TripStatus.PLANNED


@pytest.mark.parametrize("user_id", [CREATOR, GUEST])
def test_duplicate_membership_is_rejected_without_changing_participants(trip, user_id):
    admit(trip, GUEST, requested_by=CREATOR)
    before = trip.participants
    with pytest.raises(ValueError):
        admit(trip, user_id, requested_by=CREATOR)
    assert trip.participants == before


@pytest.mark.parametrize("actor", [GUEST, UserId("outsider")])
def test_only_creator_can_add_participants(trip, actor):
    admit(trip, GUEST, requested_by=CREATOR)
    before = trip.participants
    with pytest.raises(ValueError):
        admit(trip, UserId("new-user"), requested_by=actor)
    assert trip.participants == before


def test_participant_collection_is_an_immutable_snapshot(trip):
    snapshot = trip.participants
    with pytest.raises(AttributeError):
        snapshot.clear()
    admit(trip, GUEST, requested_by=CREATOR)
    assert snapshot == frozenset({Participant(trip.id, CREATOR)})
    assert len(trip.participants) == 2


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("id", TripId("other")),
        ("name", "Other trip"),
        ("creator_id", GUEST),
        ("period", TripPeriod(END, END)),
        ("invitation_code", InvitationCode("other")),
        ("description", "Other description"),
        ("status", TripStatus.ACTIVE),
        ("status", TripStatus.COMPLETED),
        ("status", TripStatus.ARCHIVED),
        ("participants", frozenset()),
    ],
)
def test_aggregate_state_cannot_be_reassigned_directly(trip, attribute, value):
    with pytest.raises(AttributeError):
        setattr(trip, attribute, value)


@pytest.mark.parametrize("today", [START, END, date(2026, 10, 16)])
def test_creator_can_activate_on_or_after_start_date(trip, today):
    admit(trip, GUEST, requested_by=CREATOR)
    before = trip.participants
    trip.activate(requested_by=CREATOR, current_date=today)
    assert trip.status is TripStatus.ACTIVE
    assert trip.participants == before


def test_activation_before_start_date_is_rejected(trip):
    admit(trip, GUEST, requested_by=CREATOR)
    with pytest.raises(ValueError):
        trip.activate(requested_by=CREATOR, current_date=date(2026, 10, 9))
    assert trip.status is TripStatus.PLANNED


def test_activation_requires_at_least_two_participants(trip):
    with pytest.raises(ValueError):
        trip.activate(requested_by=CREATOR, current_date=START)
    assert trip.status is TripStatus.PLANNED


@pytest.mark.parametrize("actor", [GUEST, UserId("outsider")])
def test_only_creator_can_activate(trip, actor):
    admit(trip, GUEST, requested_by=CREATOR)
    with pytest.raises(ValueError):
        trip.activate(requested_by=actor, current_date=START)
    assert trip.status is TripStatus.PLANNED


def test_active_trip_cannot_be_activated_again(trip):
    admit(trip, GUEST, requested_by=CREATOR)
    trip.activate(requested_by=CREATOR, current_date=START)
    with pytest.raises(ValueError):
        trip.activate(requested_by=CREATOR, current_date=START)
    assert trip.status is TripStatus.ACTIVE


def test_active_trip_membership_is_locked(trip):
    admit(trip, GUEST, requested_by=CREATOR)
    trip.activate(requested_by=CREATOR, current_date=START)
    before = trip.participants
    with pytest.raises(ValueError):
        admit(trip, UserId("late-guest"), requested_by=CREATOR)
    assert trip.participants == before


def test_active_trip_cannot_return_to_planned(trip):
    admit(trip, GUEST, requested_by=CREATOR)
    trip.activate(requested_by=CREATOR, current_date=START)
    with pytest.raises(AttributeError):
        trip.status = TripStatus.PLANNED
    assert trip.status is TripStatus.ACTIVE


def test_membership_is_owned_by_each_trip(trip):
    other = Trip(
        TripId("other"), "Other", CREATOR, TripPeriod(END, END), InvitationCode("other")
    )
    admit(trip, GUEST, requested_by=CREATOR)
    assert other.participants == frozenset({Participant(other.id, CREATOR)})
