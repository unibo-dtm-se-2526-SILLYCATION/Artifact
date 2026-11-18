"""Internal write routes exercise existing use cases; no production auth bypass."""

from datetime import date, timedelta
from unittest.mock import Mock
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api.dependencies import (
    get_activate_trip,
    get_approve_join_request,
    get_archive_trip,
    get_authenticated_user_id,
    get_complete_trip,
    get_create_trip,
    get_current_date,
    get_episode_repository,
    get_new_invitation_code,
    get_new_join_request_id,
    get_new_trip_id,
    get_reject_join_request,
    get_request_join_trip,
    get_trip_repository,
    get_user_repository,
)
from sillycation.adapters.api.routes.trips import router
from sillycation.application.ports.repositories import (
    EpisodeRepository,
    TripRepository,
    UserRepository,
)
from sillycation.application.trip_use_cases import (
    ActivateTrip,
    ApproveJoinRequest,
    ArchiveTrip,
    CompleteTrip,
    CreateTrip,
    RejectJoinRequest,
    RequestJoinTrip,
)
from sillycation.domain.episode import Episode
from sillycation.domain.errors import InvalidState, NotAuthorized
from sillycation.domain.identifiers import EpisodeId, JoinRequestId, TripId, UserId
from sillycation.domain.trip import JoinRequest, Participant, Trip, TripStatus
from sillycation.domain.user import User
from sillycation.domain.value_objects import InvitationCode, TripPeriod

DAY = date(2026, 11, 10)
CREATOR = UserId("creator")
MEMBER = UserId("member")
APPLICANT = UserId("applicant")
NEW_TRIP = TripId("generated-trip")
NEW_REQUEST = JoinRequestId("generated-request")
NEW_CODE = InvitationCode("GENERATED")
BODY = {"name": "Roma", "start_date": "2026-11-10", "end_date": "2026-11-10"}
APPROVE = "/api/v1/trips/trip/join-requests/pending/approve"
REJECT = "/api/v1/trips/trip/join-requests/pending/reject"
OPERATIONS = [
    ("/api/v1/trips", BODY, get_create_trip, CreateTrip, 201),
    (
        "/api/v1/join-requests",
        {"invitation_code": "CODE"},
        get_request_join_trip,
        RequestJoinTrip,
        201,
    ),
    (APPROVE, None, get_approve_join_request, ApproveJoinRequest, 200),
    (REJECT, None, get_reject_join_request, RejectJoinRequest, 200),
    ("/api/v1/trips/trip/activate", None, get_activate_trip, ActivateTrip, 200),
    ("/api/v1/trips/trip/complete", None, get_complete_trip, CompleteTrip, 200),
    ("/api/v1/trips/trip/archive", None, get_archive_trip, ArchiveTrip, 200),
]


@pytest.fixture
def data():
    trip = Trip(
        TripId("trip"), "Trip", CREATOR, TripPeriod(DAY, DAY), InvitationCode("CODE")
    )
    trip.request_to_join(JoinRequestId("member-request"), MEMBER)
    trip.approve_join_request(JoinRequestId("member-request"), requested_by=CREATOR)
    trip.request_to_join(JoinRequestId("pending"), APPLICANT)
    stored = {trip.id: trip}
    trips = Mock(spec=TripRepository)
    trips.get_by_id.side_effect = stored.get
    trips.get_by_invitation_code.side_effect = lambda code: next(
        (item for item in stored.values() if item.invitation_code == code), None
    )
    trips.find_active_or_planned_trips_by_participant.return_value = []

    def save(item):
        stored[item.id] = item
        return item

    trips.save.side_effect = save
    users = Mock(spec=UserRepository)
    users.get_by_id.side_effect = lambda identity: (
        User(identity, identity.value, identity.value + "@example.org", "hash")
        if identity in (CREATOR, MEMBER, APPLICANT)
        else None
    )
    episodes = Mock(spec=EpisodeRepository)
    episodes.find_unresolved_by_trip.return_value = []
    return trip, trips, users, episodes, stored


def internal_app(data, actor=CREATOR):
    _, trips, users, episodes, _ = data
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides.update(
        {
            get_authenticated_user_id: lambda: actor,
            get_trip_repository: lambda: trips,
            get_user_repository: lambda: users,
            get_episode_repository: lambda: episodes,
            get_new_trip_id: lambda: NEW_TRIP,
            get_new_join_request_id: lambda: NEW_REQUEST,
            get_new_invitation_code: lambda: NEW_CODE,
            get_current_date: lambda: DAY,
        }
    )
    return app


@pytest.mark.parametrize("path,body,provider,case_type,expected_status", OPERATIONS)
def test_writes_are_not_mounted_in_public_factory(
    path, body, provider, case_type, expected_status
) -> None:
    with TestClient(create_app()) as client:
        assert client.post(path, json=body).status_code == 404
        assert client.get("/openapi.json").json()["paths"] == {}


@pytest.mark.parametrize("path,body,provider,case_type,expected_status", OPERATIONS)
@pytest.mark.parametrize(
    "headers", [{}, {"X-User-ID": "creator"}, {"Authorization": "Bearer invented"}]
)
def test_gate_blocks_before_use_cases_repositories_and_generators(
    path, body, provider, case_type, expected_status, headers
) -> None:
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    forbidden = Mock(
        side_effect=AssertionError("Must not resolve protected dependencies")
    )
    app.dependency_overrides[provider] = forbidden
    for generator in (
        get_new_trip_id,
        get_new_join_request_id,
        get_new_invitation_code,
        get_current_date,
    ):
        app.dependency_overrides[generator] = forbidden
    with TestClient(app) as client:
        response = client.post(
            path,
            json=body,
            headers=headers,
            params={"actor": "creator", "requested_by": "creator"},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "Protected API is not configured"}
    forbidden.assert_not_called()


@pytest.mark.parametrize("path,body,provider,case_type,expected_status", OPERATIONS)
def test_each_route_delegates_exactly_to_existing_use_case(
    data, path, body, provider, case_type, expected_status
) -> None:
    trip, _, _, _, _ = data
    use_case = Mock(spec=case_type)
    use_case.execute.return_value = (
        JoinRequest(NEW_REQUEST, trip.id, MEMBER)
        if case_type in (RequestJoinTrip, ApproveJoinRequest, RejectJoinRequest)
        else trip
    )
    app = internal_app(data, MEMBER)
    app.dependency_overrides[provider] = lambda: use_case
    with TestClient(app) as client:
        response = client.post(
            path,
            json=body,
            params={
                "actor": "creator",
                "requested_by": "creator",
                "current_date": "2099-01-01",
                "trip_id": "spoofed",
                "request_id": "spoofed",
                "invitation_code": "spoofed",
            },
            headers={"X-User-ID": "creator"},
        )
    assert response.status_code == expected_status
    if case_type is CreateTrip:
        expected = dict(
            trip_id=NEW_TRIP,
            name="Roma",
            creator_id=MEMBER,
            start_date=DAY,
            end_date=DAY,
            invitation_code=NEW_CODE,
            description=None,
        )
    elif case_type is RequestJoinTrip:
        expected = dict(
            invitation_code=InvitationCode("CODE"),
            request_id=NEW_REQUEST,
            user_id=MEMBER,
        )
    else:
        expected = dict(trip_id=trip.id, requested_by=MEMBER)
        if case_type in (ApproveJoinRequest, RejectJoinRequest):
            expected["request_id"] = JoinRequestId("pending")
        if case_type in (ActivateTrip, CompleteTrip):
            expected["current_date"] = DAY
    use_case.execute.assert_called_once_with(**expected)
    assert "invitation_code" not in response.json()


def test_full_trip_write_workflow_with_real_use_cases(data) -> None:
    with TestClient(internal_app(data)) as creator:
        response = creator.post(
            "/api/v1/trips", json={**BODY, "description": "Holiday"}
        )
        assert response.status_code == 201
        assert response.json() == {
            "id": NEW_TRIP.value,
            "name": "Roma",
            "creator_id": CREATOR.value,
            "start_date": "2026-11-10",
            "end_date": "2026-11-10",
            "status": "PLANNED",
            "description": "Holiday",
        }
    _, trips, _, episodes, stored = data
    assert stored[NEW_TRIP].participants == {Participant(NEW_TRIP, CREATOR)}
    with TestClient(internal_app(data, MEMBER)) as member:
        response = member.post(
            "/api/v1/join-requests", json={"invitation_code": NEW_CODE.value}
        )
        assert response.status_code == 201
        assert response.json() == {
            "id": NEW_REQUEST.value,
            "trip_id": NEW_TRIP.value,
            "user_id": MEMBER.value,
            "status": "PENDING",
        }
    with TestClient(internal_app(data)) as creator:
        prefix = "/api/v1/trips/" + NEW_TRIP.value
        response = creator.post(
            prefix + "/join-requests/" + NEW_REQUEST.value + "/approve"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "APPROVED"
        for action, state in [
            ("activate", "ACTIVE"),
            ("complete", "COMPLETED"),
            ("archive", "ARCHIVED"),
        ]:
            response = creator.post(prefix + "/" + action)
            assert response.status_code == 200
            assert response.json()["status"] == state
    assert trips.save.call_count == 6
    episodes.find_unresolved_by_trip.assert_called_once_with(NEW_TRIP)


def test_creator_rejection_does_not_add_participant(data) -> None:
    trip, _, _, _, _ = data
    with TestClient(internal_app(data)) as client:
        response = client.post(REJECT)
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    assert Participant(trip.id, APPLICANT) not in trip.participants


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"start_date": "invalid"},
        {"end_date": None},
        {"creator_id": "spoofed"},
        {"trip_id": "spoofed"},
        {"invitation_code": "spoofed"},
        {"status": "ACTIVE"},
    ],
)
def test_create_rejects_invalid_http_input_without_execution(data, changes) -> None:
    use_case = Mock(spec=CreateTrip)
    app = internal_app(data)
    app.dependency_overrides[get_create_trip] = lambda: use_case
    with TestClient(app) as client:
        assert client.post("/api/v1/trips", json={**BODY, **changes}).status_code == 422
    use_case.execute.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"invitation_code": " "},
        {"invitation_code": 7},
        {"invitation_code": "CODE", "user_id": "creator"},
    ],
)
def test_join_validates_body_without_execution(data, body) -> None:
    use_case = Mock(spec=RequestJoinTrip)
    app = internal_app(data)
    app.dependency_overrides[get_request_join_trip] = lambda: use_case
    with TestClient(app) as client:
        assert client.post("/api/v1/join-requests", json=body).status_code == 422
    use_case.execute.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        APPROVE,
        REJECT,
        "/api/v1/trips/trip/activate",
        "/api/v1/trips/trip/complete",
        "/api/v1/trips/trip/archive",
    ],
)
@pytest.mark.parametrize("actor", [MEMBER, APPLICANT])
def test_only_creator_can_manage_trip_and_query_or_body_cannot_spoof_actor(
    data, path, actor
) -> None:
    trip, trips, _, _, _ = data
    before = (trip.status, trip.participants, trip.join_requests)
    with TestClient(internal_app(data, actor)) as client:
        with pytest.raises(NotAuthorized):
            client.post(
                path,
                params={"requested_by": "creator"},
                json={"requested_by": "creator"},
                headers={"X-User-ID": "creator"},
            )
    assert (trip.status, trip.participants, trip.join_requests) == before
    trips.save.assert_not_called()


def test_domain_rejects_inverted_period_without_saving(data) -> None:
    _, trips, _, _, _ = data
    with TestClient(internal_app(data)) as client:
        with pytest.raises(ValueError):
            client.post("/api/v1/trips", json={**BODY, "end_date": "2026-11-09"})
    trips.save.assert_not_called()


def test_overlap_on_create_propagates_without_temporary_http_mapping(data) -> None:
    trip, trips, _, _, _ = data
    trips.find_active_or_planned_trips_by_participant.return_value = [trip]
    with TestClient(internal_app(data)) as client:
        with pytest.raises(InvalidState):
            client.post("/api/v1/trips", json=BODY)
    trips.save.assert_not_called()


def test_unknown_invitation_propagates_lookup_error(data) -> None:
    _, trips, _, _, _ = data
    with TestClient(internal_app(data, APPLICANT)) as client:
        with pytest.raises(LookupError):
            client.post("/api/v1/join-requests", json={"invitation_code": "UNKNOWN"})
    trips.save.assert_not_called()


def test_approval_reports_existing_use_case_rejection_on_new_overlap(data) -> None:
    trip, trips, _, _, _ = data
    conflict = Trip(
        TripId("conflict"), "Conflict", APPLICANT, trip.period, InvitationCode("OTHER")
    )
    trips.find_active_or_planned_trips_by_participant.return_value = [conflict]
    with TestClient(internal_app(data)) as client:
        response = client.post(APPROVE)
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    assert Participant(trip.id, APPLICANT) not in trip.participants


def test_server_clock_cannot_be_overridden_to_activate_early(data) -> None:
    trip, trips, _, _, _ = data
    app = internal_app(data)
    app.dependency_overrides[get_current_date] = lambda: DAY - timedelta(days=1)
    with TestClient(app) as client:
        with pytest.raises(ValueError):
            client.post("/api/v1/trips/trip/activate?current_date=2099-01-01")
    assert trip.status is TripStatus.PLANNED
    trips.save.assert_not_called()


def test_completion_delegates_unresolved_episode_check(data) -> None:
    trip, trips, _, episodes, _ = data
    trip.activate(requested_by=CREATOR, current_date=DAY)
    episodes.find_unresolved_by_trip.return_value = [
        Episode(EpisodeId("draft"), trip.id, CREATOR, MEMBER, "Title", "Details", DAY)
    ]
    with TestClient(internal_app(data)) as client:
        with pytest.raises(ValueError):
            client.post("/api/v1/trips/trip/complete")
    assert trip.status is TripStatus.ACTIVE
    episodes.find_unresolved_by_trip.assert_called_once_with(trip.id)
    trips.save.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        APPROVE,
        REJECT,
        "/api/v1/trips/trip/activate",
        "/api/v1/trips/trip/complete",
        "/api/v1/trips/trip/archive",
    ],
)
def test_unknown_trip_propagates_without_saving(data, path) -> None:
    _, trips, _, _, _ = data
    with TestClient(internal_app(data)) as client:
        with pytest.raises(LookupError):
            client.post(path.replace("/trips/trip/", "/trips/missing/"))
    trips.save.assert_not_called()


def test_providers_allocate_server_owned_values_and_repository_is_explicit(
    monkeypatch,
) -> None:
    assert isinstance(get_new_trip_id(), TripId)
    assert UUID(get_new_trip_id().value).version == 4
    assert UUID(get_new_join_request_id().value).version == 4
    token = Mock(return_value="random-code")
    monkeypatch.setattr("sillycation.adapters.api.dependencies.token_urlsafe", token)
    assert get_new_invitation_code() == InvitationCode("random-code")
    token.assert_called_once_with(12)

    class FixedDate:
        @staticmethod
        def today() -> date:
            return DAY

    monkeypatch.setattr("sillycation.adapters.api.dependencies.date", FixedDate)
    assert get_current_date() == DAY
    with pytest.raises(RuntimeError):
        get_user_repository()


def test_internal_openapi_exposes_no_actor_clock_or_generated_ids(data) -> None:
    paths = internal_app(data).openapi()["paths"]
    assert len(paths) == 7
    for path in paths.values():
        assert set(path) == {"post"}
        operation = path["post"]
        names = {parameter["name"] for parameter in operation.get("parameters", [])}
        assert names <= {"trip_id", "request_id"}
    assert create_app().openapi()["paths"] == {}
    assert create_app().dependency_overrides == {}
