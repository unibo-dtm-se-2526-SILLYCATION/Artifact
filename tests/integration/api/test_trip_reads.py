"""Internal HTTP reads with real use cases and test-only identity overrides.

The production factory never mounts these routes. Permission/lookup exceptions
are intentionally asserted as propagated exceptions until step 3 is available.
"""

from datetime import date
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from sillycation.adapters.api.app import create_app
from sillycation.adapters.api.dependencies import (
    get_authenticated_user_id,
    get_episode_repository,
    get_list_my_trips,
    get_trip_repository,
)
from sillycation.adapters.api.routes.trip_reads import router
from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.application.trip_read_use_cases import ListMyTrips
from sillycation.domain.episode import Episode
from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)
from sillycation.domain.trip import Trip
from sillycation.domain.value_objects import InvitationCode, TripPeriod, VoteValue

CREATOR = UserId("creator")
MEMBER = UserId("member")
OUTSIDER = UserId("outsider")
DAY = date(2026, 11, 10)
PATHS = [
    "/api/v1/trips",
    "/api/v1/trips/trip/invitation-code",
    "/api/v1/trips/trip/join-requests",
    "/api/v1/trips/trip/participants",
    "/api/v1/trips/trip/episodes",
    "/api/v1/trips/trip/ranking",
    "/api/v1/trips/trip/dashboard",
]


@pytest.fixture
def data():
    def make_trip(key: str) -> Trip:
        trip = Trip(
            TripId(key),
            key,
            CREATOR,
            TripPeriod(DAY, DAY),
            InvitationCode("PRIVATE-" + key),
        )
        trip.request_to_join(JoinRequestId(key + "-member"), MEMBER)
        trip.approve_join_request(JoinRequestId(key + "-member"), requested_by=CREATOR)
        trip.request_to_join(JoinRequestId(key + "-pending"), OUTSIDER)
        return trip

    trip = make_trip("trip")
    trip.activate(requested_by=CREATOR, current_date=DAY)
    archived = make_trip("archived")
    archived.activate(requested_by=CREATOR, current_date=DAY)
    archived.complete(
        requested_by=CREATOR, current_date=DAY, has_unresolved_episodes=False
    )
    archived.archive(requested_by=CREATOR)
    unrelated = Trip(
        TripId("unrelated"),
        "unrelated",
        OUTSIDER,
        TripPeriod(DAY, DAY),
        InvitationCode("X"),
    )

    own_draft = Episode(
        EpisodeId("own"), trip.id, CREATOR, MEMBER, "Own", "Details", DAY
    )
    other_draft = Episode(
        EpisodeId("other"), trip.id, MEMBER, CREATOR, "Other", "Secret", DAY
    )
    voting = Episode(
        EpisodeId("voting"), trip.id, MEMBER, CREATOR, "Voting", "Details", DAY
    )
    voting.submit(requested_by=MEMBER, trip_status=trip.status)
    completed = Episode(
        EpisodeId("completed"), trip.id, CREATOR, MEMBER, "Done", "Details", DAY
    )
    completed.submit(requested_by=CREATOR, trip_status=trip.status)
    completed.cast_vote(
        VoteId("vote"),
        CREATOR,
        VoteValue(4),
        eligible_voters={CREATOR},
        trip_status=trip.status,
    )
    trips = Mock(spec=TripRepository)
    trips.get_by_id.side_effect = lambda identity: {
        trip.id: trip,
        archived.id: archived,
        unrelated.id: unrelated,
    }.get(identity)
    # Include unrelated data to ensure the existing use case still filters it.
    trips.find_by_participant.return_value = [trip, archived, unrelated]
    episodes = Mock(spec=EpisodeRepository)
    episodes.find_by_trip.side_effect = lambda identity: (
        [own_draft, other_draft, voting, completed] if identity == trip.id else []
    )
    return trips, episodes


def internal_app(data, actor=CREATOR):
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_user_id] = lambda: actor
    trips, episodes = data
    app.dependency_overrides[get_trip_repository] = lambda: trips
    app.dependency_overrides[get_episode_repository] = lambda: episodes
    return app


@pytest.mark.parametrize("path", PATHS)
def test_production_factory_does_not_expose_protected_routes(path) -> None:
    with TestClient(create_app()) as client:
        response = client.get(
            path, params={"requested_by": "creator"}, headers={"X-User-ID": "creator"}
        )
        assert response.status_code == 404
        assert client.get("/openapi.json").json()["paths"] == {}


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-User-ID": "creator"}, {"Authorization": "Bearer invented"}],
)
def test_internal_router_blocks_access_before_any_repository_lookup(
    path, headers
) -> None:
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    # Repositories remain unconfigured: if evaluated, the test would raise.
    with TestClient(app) as client:
        response = client.get(
            path,
            headers=headers,
            params={
                "user_id": "creator",
                "actor": "creator",
                "requested_by": "creator",
            },
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "Protected API is not configured"}


def test_trip_list_uses_verified_actor_and_archive_filter(data) -> None:
    with TestClient(internal_app(data)) as client:
        response = client.get("/api/v1/trips", params={"requested_by": "outsider"})
        assert response.status_code == 200
        assert [trip["id"] for trip in response.json()] == ["trip"]
        assert "invitation_code" not in response.json()[0]
        response = client.get("/api/v1/trips?archived=true")
        assert [trip["id"] for trip in response.json()] == ["archived"]
        assert response.json()[0]["status"] == "ARCHIVED"
    trips, episodes = data
    assert trips.find_by_participant.call_args.args == (CREATOR,)
    trips.save.assert_not_called()
    episodes.save.assert_not_called()


def test_creator_can_read_invitation_and_pending_requests(data) -> None:
    with TestClient(internal_app(data)) as client:
        assert client.get(PATHS[1]).json() == {"invitation_code": "PRIVATE-trip"}
        requests = client.get(PATHS[2]).json()
        assert requests == [
            {
                "id": "trip-pending",
                "trip_id": "trip",
                "user_id": "outsider",
                "status": "PENDING",
            }
        ]


def test_member_can_read_participants_and_history(data) -> None:
    with TestClient(internal_app(data, MEMBER)) as client:
        response = client.get(PATHS[3])
        assert response.status_code == 200
        assert [item["user_id"] for item in response.json()] == ["creator", "member"]
        response = client.get("/api/v1/trips/archived/dashboard")
        assert response.status_code == 200
        assert response.json()["trip"]["status"] == "ARCHIVED"


@pytest.mark.parametrize(
    "actor,visible",
    [
        (CREATOR, ["completed", "own", "voting"]),
        (MEMBER, ["completed", "other", "voting"]),
    ],
)
def test_episode_list_and_dashboard_preserve_draft_visibility_and_scores(
    data, actor, visible
) -> None:
    with TestClient(internal_app(data, actor)) as client:
        response = client.get(PATHS[4])
        assert response.status_code == 200
        episodes = response.json()
        assert [episode["id"] for episode in episodes] == visible
        assert episodes[0]["score"] == "4"
        assert all(episode["score"] is None for episode in episodes[1:])
        assert all("votes" not in episode for episode in episodes)
        dashboard = client.get(PATHS[6])
        assert dashboard.status_code == 200
        assert dashboard.json()["episodes"] == episodes
        assert "invitation_code" not in dashboard.json()["trip"]
        ranking = client.get(PATHS[5])
        assert ranking.status_code == 200
        assert ranking.json() == [
            {"user_id": "member", "score": "4", "position": 1},
            {"user_id": "creator", "score": "0", "position": 2},
        ]
        assert dashboard.json()["ranking"] == ranking.json()


@pytest.mark.parametrize("path", PATHS[1:])
def test_non_member_cannot_spoof_identity_to_bypass_use_case_authorization(
    data, path
) -> None:
    trips, episodes = data
    with TestClient(internal_app(data, OUTSIDER)) as client:
        # The exception is not translated yet: no text-based mapping is introduced.
        with pytest.raises(PermissionError):
            client.get(
                path,
                params={
                    "actor": "creator",
                    "requested_by": "creator",
                    "user_id": "creator",
                },
                headers={"X-User-ID": "creator"},
            )
    episodes.find_by_trip.assert_not_called()
    trips.save.assert_not_called()


@pytest.mark.parametrize("path", PATHS[1:3])
def test_ordinary_member_cannot_read_creator_only_data(data, path) -> None:
    with TestClient(internal_app(data, MEMBER)) as client:
        with pytest.raises(PermissionError):
            client.get(path, params={"requested_by": "creator"})


@pytest.mark.parametrize(
    "suffix",
    [
        "participants",
        "invitation-code",
        "join-requests",
        "episodes",
        "ranking",
        "dashboard",
    ],
)
def test_unknown_trip_propagates_lookup_error_without_guessing_http_mapping(
    data, suffix
) -> None:
    with TestClient(internal_app(data)) as client:
        with pytest.raises(LookupError):
            client.get("/api/v1/trips/missing/" + suffix)


def test_use_case_can_be_overridden_and_query_does_not_select_actor() -> None:
    use_case = Mock(spec=ListMyTrips)
    use_case.execute.return_value = ()
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_authenticated_user_id] = lambda: MEMBER
    app.dependency_overrides[get_list_my_trips] = lambda: use_case
    with TestClient(app) as client:
        assert (
            client.get("/api/v1/trips?requested_by=creator&archived=true").json() == []
        )
    use_case.execute.assert_called_once_with(requested_by=MEMBER, archived=True)


def test_internal_openapi_describes_only_versioned_reads_without_actor_input(
    data,
) -> None:
    schema = internal_app(data).openapi()
    assert set(schema["paths"]) == {
        path.replace("/trips/trip/", "/trips/{trip_id}/") for path in PATHS
    }
    for path in schema["paths"].values():
        assert set(path) == {"get"}
        operation = path["get"]
        assert "200" in operation["responses"]
        assert "requestBody" not in operation
        names = {parameter["name"] for parameter in operation.get("parameters", [])}
        assert names <= {"trip_id", "archived"}


def test_overrides_are_not_shared_with_the_public_factory(data) -> None:
    internal_app(data)
    public = create_app()
    assert public.dependency_overrides == {}
    assert public.openapi()["paths"] == {}
