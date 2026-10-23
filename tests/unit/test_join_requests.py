from datetime import date

import pytest

from sillycation.domain.identifiers import JoinRequestId, TripId, UserId
from sillycation.domain.trip import JoinRequestStatus, Participant, Trip
from sillycation.domain.value_objects import InvitationCode, TripPeriod


CREATOR = UserId("creator")
APPLICANT = UserId("applicant")
REQUEST_ID = JoinRequestId("request-1")
TODAY = date(2026, 10, 23)


@pytest.fixture
def trip():
    return Trip(
        TripId("trip"),
        "Holiday",
        CREATOR,
        TripPeriod(TODAY, TODAY),
        InvitationCode("invite"),
    )


@pytest.fixture
def pending(trip):
    return trip.request_to_join(REQUEST_ID, APPLICANT)


def test_request_is_pending_and_does_not_grant_membership(trip):
    assert trip.join_requests == ()
    request = trip.request_to_join(REQUEST_ID, APPLICANT)
    assert request.id == REQUEST_ID
    assert request.trip_id == trip.id
    assert request.user_id == APPLICANT
    assert request.status is JoinRequestStatus.PENDING
    assert trip.get_join_request(REQUEST_ID) == request
    assert trip.join_requests == (request,)
    assert trip.participants == frozenset({Participant(trip.id, CREATOR)})


def test_duplicate_pending_request_is_rejected(trip, pending):
    with pytest.raises(ValueError):
        trip.request_to_join(JoinRequestId("another"), APPLICANT)
    assert trip.join_requests == (pending,)


@pytest.mark.parametrize(
    "decision", [None, "approve_join_request", "reject_join_request"]
)
def test_request_id_cannot_be_reused(trip, pending, decision):
    if decision:
        getattr(trip, decision)(REQUEST_ID, requested_by=CREATOR)
    before = trip.join_requests
    with pytest.raises(ValueError):
        trip.request_to_join(REQUEST_ID, UserId("another-user"))
    assert trip.join_requests == before
    assert trip.get_join_request(REQUEST_ID).user_id == APPLICANT


def test_multiple_users_can_have_pending_requests(trip, pending):
    other = trip.request_to_join(JoinRequestId("other"), UserId("other"))
    assert len(trip.join_requests) == 2
    assert other.trip_id == pending.trip_id


def test_approval_adds_participant_and_preserves_request_identity(trip, pending):
    trip.approve_join_request(REQUEST_ID, requested_by=CREATOR)
    approved = trip.get_join_request(REQUEST_ID)
    assert approved.id == pending.id
    assert approved.trip_id == pending.trip_id
    assert approved.user_id == pending.user_id
    assert approved.status is JoinRequestStatus.APPROVED
    assert trip.participants == frozenset(
        {
            Participant(trip.id, CREATOR),
            Participant(trip.id, APPLICANT),
        }
    )


def test_rejection_including_caller_reported_overlap_does_not_add_participant(
    trip, pending
):
    # The sequence diagram uses this same operation when a conflict is reported.
    before = trip.participants
    trip.reject_join_request(REQUEST_ID, requested_by=CREATOR)
    assert trip.get_join_request(REQUEST_ID).status is JoinRequestStatus.REJECTED
    assert trip.participants == before


@pytest.mark.parametrize("first", ["approve_join_request", "reject_join_request"])
@pytest.mark.parametrize("second", ["approve_join_request", "reject_join_request"])
def test_decided_request_cannot_be_decided_again(trip, pending, first, second):
    getattr(trip, first)(REQUEST_ID, requested_by=CREATOR)
    status = trip.get_join_request(REQUEST_ID).status
    members = trip.participants
    with pytest.raises(ValueError):
        getattr(trip, second)(REQUEST_ID, requested_by=CREATOR)
    assert trip.get_join_request(REQUEST_ID).status is status
    assert trip.participants == members


@pytest.mark.parametrize("decision", ["approve_join_request", "reject_join_request"])
@pytest.mark.parametrize("actor", [APPLICANT, UserId("outsider"), UserId("member")])
def test_only_creator_can_decide_request(trip, pending, decision, actor):
    member_request = trip.request_to_join(JoinRequestId("member"), UserId("member"))
    trip.approve_join_request(member_request.id, requested_by=CREATOR)
    before = trip.participants
    with pytest.raises(ValueError):
        getattr(trip, decision)(REQUEST_ID, requested_by=actor)
    assert trip.get_join_request(REQUEST_ID).status is JoinRequestStatus.PENDING
    assert trip.participants == before


@pytest.mark.parametrize(
    "operation", ["request", "approve_join_request", "reject_join_request"]
)
def test_requests_cannot_be_created_or_decided_after_activation(
    trip, pending, operation
):
    member = trip.request_to_join(JoinRequestId("member"), UserId("member"))
    trip.approve_join_request(member.id, requested_by=CREATOR)
    trip.activate(requested_by=CREATOR, current_date=TODAY)
    requests = trip.join_requests
    members = trip.participants
    with pytest.raises(ValueError):
        if operation == "request":
            trip.request_to_join(JoinRequestId("late"), UserId("late"))
        else:
            getattr(trip, operation)(REQUEST_ID, requested_by=CREATOR)
    assert trip.join_requests == requests
    assert trip.get_join_request(REQUEST_ID).status is JoinRequestStatus.PENDING
    assert trip.participants == members


@pytest.mark.parametrize(
    "operation", ["get_join_request", "approve_join_request", "reject_join_request"]
)
def test_unknown_or_other_trip_request_is_rejected(trip, operation):
    other = Trip(
        TripId("other"),
        "Other",
        CREATOR,
        TripPeriod(TODAY, TODAY),
        InvitationCode("other"),
    )
    other.request_to_join(REQUEST_ID, APPLICANT)
    with pytest.raises(ValueError):
        if operation == "get_join_request":
            trip.get_join_request(REQUEST_ID)
        else:
            getattr(trip, operation)(REQUEST_ID, requested_by=CREATOR)
    assert trip.join_requests == ()
    assert other.get_join_request(REQUEST_ID).status is JoinRequestStatus.PENDING


def test_rejected_user_can_make_new_request_with_new_identity(trip, pending):
    trip.reject_join_request(REQUEST_ID, requested_by=CREATOR)
    retry = trip.request_to_join(JoinRequestId("retry"), APPLICANT)
    assert retry.status is JoinRequestStatus.PENDING
    trip.approve_join_request(retry.id, requested_by=CREATOR)
    assert trip.get_join_request(REQUEST_ID).status is JoinRequestStatus.REJECTED
    assert len(trip.participants) == 2


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("id", JoinRequestId("other")),
        ("user_id", CREATOR),
        ("trip_id", TripId("other")),
        ("status", JoinRequestStatus.APPROVED),
    ],
)
def test_request_cannot_be_modified_outside_trip(trip, pending, attribute, value):
    with pytest.raises(AttributeError):
        setattr(pending, attribute, value)
    assert trip.get_join_request(REQUEST_ID).status is JoinRequestStatus.PENDING


def test_request_collection_and_snapshots_are_immutable(trip, pending):
    snapshot = trip.join_requests
    with pytest.raises(AttributeError):
        snapshot.clear()
    with pytest.raises(AttributeError):
        trip.join_requests = ()
    trip.approve_join_request(REQUEST_ID, requested_by=CREATOR)
    assert snapshot[0].status is JoinRequestStatus.PENDING
    assert trip.join_requests[0].status is JoinRequestStatus.APPROVED
