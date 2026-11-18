"""FR-09--FR-15 through internal HTTP routes and the real application layer."""

from copy import deepcopy
from datetime import date
from unittest.mock import Mock
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import IntegrityError

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api.dependencies import (
    get_authenticated_user_id,
    get_cast_vote,
    get_create_episode,
    get_delete_episode,
    get_edit_episode,
    get_episode_repository,
    get_new_episode_id,
    get_new_vote_id,
    get_submit_episode,
    get_trip_repository,
)
from sillycation.adapters.api.routes.episodes import router
from sillycation.adapters.api.routes.trip_reads import router as read_router
from sillycation.application.episode_use_cases import (
    CreateEpisode,
    DeleteEpisode,
    EditEpisode,
    SubmitEpisode,
)
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

CREATOR = UserId("creator")
MEMBER = UserId("member")
OTHER = UserId("other")
OUTSIDER = UserId("outsider")
TRIP = TripId("trip")
NEW_EPISODE = EpisodeId("generated-episode")
NEW_VOTE = VoteId("generated-vote")
DAY = date(2026, 11, 10)
BODY = {
    "title": "Lost passport",
    "description": "At the hotel",
    "date": "2026-11-10",
    "protagonist_id": "member",
}
OPERATIONS = [
    (
        "POST",
        "/api/v1/trips/trip/episodes",
        BODY,
        get_create_episode,
        CreateEpisode,
        201,
    ),
    ("PUT", "/api/v1/episodes/draft", BODY, get_edit_episode, EditEpisode, 200),
    ("DELETE", "/api/v1/episodes/draft", None, get_delete_episode, DeleteEpisode, 204),
    (
        "POST",
        "/api/v1/episodes/draft/submit",
        None,
        get_submit_episode,
        SubmitEpisode,
        200,
    ),
    (
        "POST",
        "/api/v1/episodes/draft/votes",
        {"value": 4},
        get_cast_vote,
        CastVote,
        201,
    ),
]


def make_trip(size: int = 3) -> Trip:
    trip = Trip(TRIP, "Roma", CREATOR, TripPeriod(DAY, DAY), InvitationCode("PRIVATE"))
    members = [MEMBER, OTHER] + [
        UserId("extra-" + str(i)) for i in range(max(0, size - 3))
    ]
    for member in members[: size - 1]:
        request = JoinRequestId(member.value)
        trip.request_to_join(request, member)
        trip.approve_join_request(request, requested_by=CREATOR)
    trip.activate(requested_by=CREATOR, current_date=DAY)
    return trip


def episode_in_state(status: EpisodeStatus, trip: Trip) -> Episode:
    draft = Episode(
        EpisodeId("draft"), TRIP, CREATOR, MEMBER, "Secret title", "Private draft", DAY
    )
    if status is EpisodeStatus.SUBMITTED:
        # A repository can rehydrate the documented transient SUBMITTED state.
        return Episode.restore(
            id=draft.id,
            trip_id=TRIP,
            author_id=CREATOR,
            protagonist_id=MEMBER,
            title=draft.title,
            description=draft.description,
            date=DAY,
            status=status,
            votes=(),
        )
    if status in (EpisodeStatus.VOTING, EpisodeStatus.COMPLETED):
        draft.submit(requested_by=CREATOR, trip_status=trip.status)
    if status is EpisodeStatus.COMPLETED:
        voters = {member.user_id for member in trip.participants} - {MEMBER}
        for voter in sorted(voters, key=lambda item: item.value):
            draft.cast_vote(
                VoteId(voter.value),
                voter,
                VoteValue(4),
                eligible_voters=voters,
                trip_status=trip.status,
            )
    return draft


@pytest.fixture
def data():
    trip = make_trip()
    stored = {EpisodeId("draft"): episode_in_state(EpisodeStatus.DRAFT, trip)}
    trips = Mock(spec=TripRepository)
    trips.get_by_id.side_effect = lambda identity: (
        deepcopy(trip) if identity == TRIP else None
    )
    episodes = Mock(spec=EpisodeRepository)
    # Detached snapshots ensure mutation is only persisted after save succeeds.
    episodes.get_by_id.side_effect = lambda identity: deepcopy(stored.get(identity))
    episodes.find_by_trip.side_effect = lambda identity: [
        deepcopy(item) for item in stored.values() if item.trip_id == identity
    ]

    def save(episode):
        stored[episode.id] = deepcopy(episode)
        return episode

    def delete(identity):
        del stored[identity]

    episodes.save.side_effect = save
    episodes.delete.side_effect = delete
    return trip, trips, episodes, stored


def internal_app(data, actor=CREATOR):
    _, trips, episodes, _ = data
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    app.include_router(read_router, prefix="/api/v1")
    app.dependency_overrides.update(
        {
            get_authenticated_user_id: lambda: actor,
            get_trip_repository: lambda: trips,
            get_episode_repository: lambda: episodes,
            get_new_episode_id: lambda: NEW_EPISODE,
            get_new_vote_id: lambda: NEW_VOTE,
        }
    )
    return app


@pytest.mark.parametrize(
    "method,path,body,provider,case_type,expected_status", OPERATIONS
)
def test_episode_routes_remain_unmounted_in_production(
    method, path, body, provider, case_type, expected_status
) -> None:
    with TestClient(create_app()) as client:
        assert client.request(method, path, json=body).status_code == 404
        assert client.get("/openapi.json").json()["paths"] == {}


@pytest.mark.parametrize(
    "method,path,body,provider,case_type,expected_status", OPERATIONS
)
@pytest.mark.parametrize(
    "headers", [{}, {"X-User-ID": "creator"}, {"Authorization": "Bearer invented"}]
)
def test_identity_gate_blocks_protected_dependencies(
    method, path, body, provider, case_type, expected_status, headers
) -> None:
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    forbidden = Mock(side_effect=AssertionError("Protected dependency must not run"))
    for dependency in (provider, get_new_episode_id, get_new_vote_id):
        app.dependency_overrides[dependency] = forbidden
    with TestClient(app) as client:
        response = client.request(
            method,
            path,
            json=body,
            headers=headers,
            params={"actor": "creator", "requested_by": "creator"},
        )
    assert response.status_code == 503
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    "method,path,body,provider,case_type,expected_status", OPERATIONS
)
def test_routes_delegate_actor_and_server_ids_without_query_spoofing(
    data, method, path, body, provider, case_type, expected_status
) -> None:
    _, _, _, stored = data
    use_case = Mock(spec=case_type)
    use_case.execute.return_value = (
        None if case_type is DeleteEpisode else stored[EpisodeId("draft")]
    )
    app = internal_app(data, OTHER)
    app.dependency_overrides[provider] = lambda: use_case
    with TestClient(app) as client:
        response = client.request(
            method,
            path,
            json=body,
            params={
                "actor": "creator",
                "requested_by": "creator",
                "author_id": "creator",
                "voter_id": "creator",
                "episode_id": "spoofed",
                "vote_id": "spoofed",
            },
            headers={"X-User-ID": "creator"},
        )
    assert response.status_code == expected_status
    if case_type is CreateEpisode:
        expected = dict(
            episode_id=NEW_EPISODE,
            trip_id=TRIP,
            author_id=OTHER,
            protagonist_id=MEMBER,
            title=BODY["title"],
            description=BODY["description"],
            date=DAY,
        )
    elif case_type is EditEpisode:
        expected = dict(
            episode_id=EpisodeId("draft"),
            requested_by=OTHER,
            protagonist_id=MEMBER,
            title=BODY["title"],
            description=BODY["description"],
            date=DAY,
        )
    elif case_type is CastVote:
        expected = dict(
            episode_id=EpisodeId("draft"), voter_id=OTHER, vote_id=NEW_VOTE, value=4
        )
    else:
        expected = dict(episode_id=EpisodeId("draft"), requested_by=OTHER)
    use_case.execute.assert_called_once_with(**expected)
    if case_type is DeleteEpisode:
        assert response.content == b""


def test_create_edit_submit_and_vote_workflow_uses_real_domain_rules(data) -> None:
    _, _, episodes, stored = data
    with TestClient(internal_app(data)) as author:
        created = author.post("/api/v1/trips/trip/episodes", json=BODY)
        assert created.status_code == 201
        assert created.json() == {
            "id": NEW_EPISODE.value,
            "trip_id": "trip",
            "author_id": "creator",
            "protagonist_id": "member",
            "title": "Lost passport",
            "description": "At the hotel",
            "date": "2026-11-10",
            "status": "DRAFT",
            "score": None,
        }
        path = "/api/v1/episodes/" + NEW_EPISODE.value
        edited = author.put(path, json={**BODY, "title": "Found passport"})
        assert edited.status_code == 200
        assert edited.json()["title"] == "Found passport"
        submitted = author.post(path + "/submit")
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "VOTING"
        first_vote = author.post(path + "/votes", json={"value": 5})
        assert first_vote.status_code == 201
        assert first_vote.json()["status"] == "VOTING"
        assert first_vote.json()["score"] is None
    app = internal_app(data, OTHER)
    app.dependency_overrides[get_new_vote_id] = lambda: VoteId("other-vote")
    with TestClient(app) as other:
        last_vote = other.post(path + "/votes", json={"value": 4})
    assert last_vote.status_code == 201
    assert last_vote.json()["status"] == "COMPLETED"
    assert last_vote.json()["score"] == "4.5"
    assert "votes" not in last_vote.json()
    assert len(stored[NEW_EPISODE].votes) == 2
    assert episodes.save.call_count == 5


def test_author_can_delete_only_target_draft_and_delete_returns_empty_body(
    data,
) -> None:
    _, _, episodes, stored = data
    with TestClient(internal_app(data)) as client:
        client.post("/api/v1/trips/trip/episodes", json=BODY)
        response = client.delete("/api/v1/episodes/draft")
        assert response.status_code == 204
        assert response.content == b""
        assert client.delete("/api/v1/episodes/draft").status_code == 404
    assert EpisodeId("draft") not in stored
    assert NEW_EPISODE in stored
    episodes.delete.assert_called_once_with(EpisodeId("draft"))


@pytest.mark.parametrize("actor", [MEMBER, OTHER, OUTSIDER])
@pytest.mark.parametrize(
    "method,suffix,body",
    [("PUT", "", BODY), ("DELETE", "", None), ("POST", "/submit", None)],
)
def test_non_author_cannot_modify_or_disclose_private_draft(
    data, actor, method, suffix, body
) -> None:
    _, _, episodes, stored = data
    before = deepcopy(vars(stored[EpisodeId("draft")]))
    with TestClient(internal_app(data, actor)) as client:
        response = client.request(
            method,
            "/api/v1/episodes/draft" + suffix,
            json=body,
            params={"requested_by": "creator"},
            headers={"X-User-ID": "creator"},
        )
    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "not_authorized", "message": "Operation not permitted."}
    }
    assert "Secret title" not in response.text
    assert "Private draft" not in response.text
    assert vars(stored[EpisodeId("draft")]) == before
    episodes.save.assert_not_called()
    episodes.delete.assert_not_called()


def test_draft_visibility_changes_only_after_author_submission(data) -> None:
    with TestClient(internal_app(data, MEMBER)) as member:
        assert member.get("/api/v1/trips/trip/episodes").json() == []
        assert member.get("/api/v1/trips/trip/dashboard").json()["episodes"] == []
    with TestClient(internal_app(data)) as author:
        assert author.get("/api/v1/trips/trip/episodes").json()[0]["id"] == "draft"
        assert author.post("/api/v1/episodes/draft/submit").status_code == 200
    with TestClient(internal_app(data, MEMBER)) as member:
        visible = member.get("/api/v1/trips/trip/episodes").json()
        assert visible[0]["status"] == "VOTING"
        assert visible[0]["score"] is None
        assert member.get("/api/v1/trips/trip/dashboard").json()["episodes"] == visible


@pytest.mark.parametrize(
    "status", [EpisodeStatus.SUBMITTED, EpisodeStatus.VOTING, EpisodeStatus.COMPLETED]
)
@pytest.mark.parametrize(
    "method,suffix,body",
    [("PUT", "", BODY), ("DELETE", "", None), ("POST", "/submit", None)],
)
def test_submitted_and_later_episodes_are_immutable(
    data, status, method, suffix, body
) -> None:
    trip, _, episodes, stored = data
    stored[EpisodeId("draft")] = episode_in_state(status, trip)
    before = deepcopy(vars(stored[EpisodeId("draft")]))
    with TestClient(internal_app(data)) as client:
        response = client.request(method, "/api/v1/episodes/draft" + suffix, json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"
    assert vars(stored[EpisodeId("draft")]) == before
    episodes.save.assert_not_called()
    episodes.delete.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"title": " "},
        {"description": ""},
        {"date": "bad"},
        {"protagonist_id": ""},
        {"author_id": "spoofed"},
        {"episode_id": "spoofed"},
        {"status": "COMPLETED"},
    ],
)
@pytest.mark.parametrize(
    "method,path,provider,case_type",
    [
        ("POST", "/api/v1/trips/trip/episodes", get_create_episode, CreateEpisode),
        ("PUT", "/api/v1/episodes/draft", get_edit_episode, EditEpisode),
    ],
)
def test_episode_body_validation_rejects_bad_and_server_owned_fields(
    data, changes, method, path, provider, case_type
) -> None:
    use_case = Mock(spec=case_type)
    app = internal_app(data)
    app.dependency_overrides[provider] = lambda: use_case
    with TestClient(app) as client:
        response = client.request(method, path, json={**BODY, **changes})
    assert response.status_code == 422
    assert "detail" in response.json()
    use_case.execute.assert_not_called()


@pytest.mark.parametrize(
    "method,path",
    [("POST", "/api/v1/trips/trip/episodes"), ("PUT", "/api/v1/episodes/draft")],
)
@pytest.mark.parametrize(
    "changes",
    [{"date": "2026-11-09"}, {"date": "2026-11-11"}, {"protagonist_id": "outsider"}],
)
def test_episode_cross_aggregate_validation_is_delegated_to_use_case(
    data, method, path, changes
) -> None:
    _, _, episodes, stored = data
    before = deepcopy(vars(stored[EpisodeId("draft")]))
    with TestClient(internal_app(data)) as client:
        response = client.request(method, path, json={**BODY, **changes})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_data"
    assert vars(stored[EpisodeId("draft")]) == before
    episodes.save.assert_not_called()


def test_outsider_cannot_create_episode(data) -> None:
    _, _, episodes, _ = data
    with TestClient(internal_app(data, OUTSIDER)) as client:
        response = client.post("/api/v1/trips/trip/episodes", json=BODY)
    assert response.status_code == 403
    episodes.save.assert_not_called()


@pytest.mark.parametrize(
    "value", [True, False, "3", "", 3.0, 2.5, 0, 6, -1, None, [], {}]
)
def test_vote_http_input_requires_integer_one_to_five(data, value) -> None:
    use_case = Mock(spec=CastVote)
    app = internal_app(data)
    app.dependency_overrides[get_cast_vote] = lambda: use_case
    with TestClient(app) as client:
        response = client.post("/api/v1/episodes/draft/votes", json={"value": value})
    assert response.status_code == 422
    assert "detail" in response.json()
    use_case.execute.assert_not_called()


@pytest.mark.parametrize(
    "body", [{}, {"value": 3, "voter_id": "creator"}, {"value": 3, "vote_id": "chosen"}]
)
def test_vote_rejects_missing_value_and_client_owned_identity(data, body) -> None:
    with TestClient(internal_app(data)) as client:
        assert client.post("/api/v1/episodes/draft/votes", json=body).status_code == 422


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5])
def test_author_can_cast_every_valid_vote_when_not_protagonist(data, value) -> None:
    trip, _, _, stored = data
    stored[EpisodeId("draft")] = episode_in_state(EpisodeStatus.VOTING, trip)
    with TestClient(internal_app(data)) as client:
        response = client.post("/api/v1/episodes/draft/votes", json={"value": value})
    assert response.status_code == 201
    assert response.json()["status"] == "VOTING"
    assert stored[EpisodeId("draft")].votes[0].value.value == value


@pytest.mark.parametrize("actor", [MEMBER, OUTSIDER])
def test_protagonist_and_outsider_cannot_vote(data, actor) -> None:
    trip, _, episodes, stored = data
    stored[EpisodeId("draft")] = episode_in_state(EpisodeStatus.VOTING, trip)
    with TestClient(internal_app(data, actor)) as client:
        response = client.post(
            "/api/v1/episodes/draft/votes",
            json={"value": 4},
            params={"voter_id": "creator"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authorized"
    assert stored[EpisodeId("draft")].votes == ()
    episodes.save.assert_not_called()


def test_author_who_is_also_protagonist_cannot_vote(data) -> None:
    trip, _, episodes, stored = data
    own = Episode(EpisodeId("own"), TRIP, CREATOR, CREATOR, "Own", "Details", DAY)
    own.submit(requested_by=CREATOR, trip_status=trip.status)
    stored[own.id] = own
    with TestClient(internal_app(data)) as client:
        assert (
            client.post("/api/v1/episodes/own/votes", json={"value": 4}).status_code
            == 403
        )
    episodes.save.assert_not_called()


def test_duplicate_vote_is_rejected_without_changing_previous_value(data) -> None:
    trip, _, episodes, stored = data
    stored[EpisodeId("draft")] = episode_in_state(EpisodeStatus.VOTING, trip)
    with TestClient(internal_app(data)) as client:
        assert (
            client.post("/api/v1/episodes/draft/votes", json={"value": 2}).status_code
            == 201
        )
        response = client.post("/api/v1/episodes/draft/votes", json={"value": 5})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"
    assert [vote.value.value for vote in stored[EpisodeId("draft")].votes] == [2]
    assert episodes.save.call_count == 1


@pytest.mark.parametrize(
    "status", [EpisodeStatus.DRAFT, EpisodeStatus.SUBMITTED, EpisodeStatus.COMPLETED]
)
def test_votes_are_rejected_outside_voting(data, status) -> None:
    trip, _, episodes, stored = data
    stored[EpisodeId("draft")] = episode_in_state(status, trip)
    before = stored[EpisodeId("draft")].votes
    with TestClient(internal_app(data)) as client:
        response = client.post("/api/v1/episodes/draft/votes", json={"value": 4})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"
    assert stored[EpisodeId("draft")].votes == before
    episodes.save.assert_not_called()


@pytest.mark.parametrize("size", [2, 3, 5])
def test_last_eligible_vote_automatically_completes_different_group_sizes(
    data, size
) -> None:
    _, trips, _, stored = data
    trip = make_trip(size)
    trips.get_by_id.return_value = trip
    trips.get_by_id.side_effect = None
    stored[EpisodeId("draft")] = episode_in_state(EpisodeStatus.VOTING, trip)
    voters = sorted(
        {member.user_id for member in trip.participants} - {MEMBER},
        key=lambda user: user.value,
    )
    for index, voter in enumerate(voters):
        app = internal_app(data, voter)
        app.dependency_overrides[get_new_vote_id] = lambda voter=voter: VoteId(
            "vote-" + voter.value
        )
        with TestClient(app) as client:
            response = client.post("/api/v1/episodes/draft/votes", json={"value": 3})
        assert response.status_code == 201
        last = index == len(voters) - 1
        assert response.json()["status"] == ("COMPLETED" if last else "VOTING")
        assert response.json()["score"] == ("3" if last else None)


@pytest.mark.parametrize(
    "status", [TripStatus.PLANNED, TripStatus.COMPLETED, TripStatus.ARCHIVED]
)
@pytest.mark.parametrize(
    "method,path,body,provider,case_type,expected_status", OPERATIONS
)
def test_game_writes_are_rejected_for_non_active_trip(
    data, status, method, path, body, provider, case_type, expected_status
) -> None:
    trip, trips, episodes, stored = data
    if status is TripStatus.PLANNED:
        trip = Trip(TRIP, "Planned", CREATOR, trip.period, InvitationCode("CODE"))
    else:
        # Closed trips contain resolved episodes only, matching real invariants.
        stored[EpisodeId("draft")] = episode_in_state(EpisodeStatus.COMPLETED, trip)
        trip.complete(
            requested_by=CREATOR, current_date=DAY, has_unresolved_episodes=False
        )
        if status is TripStatus.ARCHIVED:
            trip.archive(requested_by=CREATOR)
    trips.get_by_id.side_effect = None
    trips.get_by_id.return_value = trip
    with TestClient(internal_app(data)) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 409
    episodes.save.assert_not_called()
    episodes.delete.assert_not_called()


@pytest.mark.parametrize(
    "method,path,body,provider,case_type,expected_status", OPERATIONS
)
def test_missing_resources_return_not_found_without_writes(
    data, method, path, body, provider, case_type, expected_status
) -> None:
    _, _, episodes, _ = data
    path = path.replace("/trips/trip/", "/trips/missing/").replace(
        "/episodes/draft", "/episodes/missing"
    )
    with TestClient(internal_app(data)) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    episodes.save.assert_not_called()
    episodes.delete.assert_not_called()


def test_generated_episode_id_collision_returns_duplicate(data) -> None:
    _, _, episodes, _ = data
    app = internal_app(data)
    app.dependency_overrides[get_new_episode_id] = lambda: EpisodeId("draft")
    with TestClient(app) as client:
        response = client.post("/api/v1/trips/trip/episodes", json=BODY)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"
    episodes.save.assert_not_called()


def test_sql_failure_is_not_mapped_to_a_business_conflict(data) -> None:
    _, _, episodes, stored = data
    episodes.save.side_effect = IntegrityError(
        "SQL PRIVATE", {}, RuntimeError("PRIVATE")
    )
    with TestClient(internal_app(data), raise_server_exceptions=False) as client:
        response = client.post("/api/v1/trips/trip/episodes", json=BODY)
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert NEW_EPISODE not in stored


def test_id_providers_allocate_uuid4_values() -> None:
    assert isinstance(get_new_episode_id(), EpisodeId)
    assert isinstance(get_new_vote_id(), VoteId)
    assert UUID(get_new_episode_id().value).version == 4
    assert UUID(get_new_vote_id().value).version == 4


def test_internal_openapi_has_only_five_operations_and_no_actor_input(data) -> None:
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    paths = app.openapi()["paths"]
    operations = [
        (path, method, operation)
        for path, item in paths.items()
        for method, operation in item.items()
    ]
    assert len(operations) == 5
    assert {(path, method) for path, method, _ in operations} == {
        ("/api/v1/trips/{trip_id}/episodes", "post"),
        ("/api/v1/episodes/{episode_id}", "put"),
        ("/api/v1/episodes/{episode_id}", "delete"),
        ("/api/v1/episodes/{episode_id}/submit", "post"),
        ("/api/v1/episodes/{episode_id}/votes", "post"),
    }
    for _, _, operation in operations:
        names = {parameter["name"] for parameter in operation.get("parameters", [])}
        assert names <= {"trip_id", "episode_id"}
    assert (
        "content"
        not in paths["/api/v1/episodes/{episode_id}"]["delete"]["responses"]["204"]
    )
    assert create_app().openapi()["paths"] == {}
    assert create_app().dependency_overrides == {}
