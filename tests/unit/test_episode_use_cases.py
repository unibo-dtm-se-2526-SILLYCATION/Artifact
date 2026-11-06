from copy import deepcopy
from datetime import date
from typing import Optional, Sequence

import pytest

from sillycation.application.episode_use_cases import (
    CreateEpisode,
    DeleteEpisode,
    EditEpisode,
    EpisodeApplicationError,
    SubmitEpisode,
)
from sillycation.application.ports.repositories import EpisodeRepository, TripRepository
from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.identifiers import EpisodeId, JoinRequestId, TripId, UserId
from sillycation.domain.trip import Trip, TripStatus
from sillycation.domain.value_objects import InvitationCode, TripPeriod


AUTHOR = UserId("author")
PROTAGONIST = UserId("protagonist")
START = date(2026, 11, 1)
END = date(2026, 11, 3)
EPISODE_ID = EpisodeId("episode")


class MemoryTrips:
    def __init__(self, trip: Trip) -> None:
        self.stored = {trip.id: deepcopy(trip)}
        self.lookups: list[TripId] = []

    def get_by_id(self, trip_id: TripId) -> Optional[Trip]:
        self.lookups.append(trip_id)
        return deepcopy(self.stored.get(trip_id))

    def save(self, trip: Trip) -> Trip:
        raise AssertionError("Episode workflows must not save Trip")

    def get_by_invitation_code(self, invitation_code: InvitationCode) -> Optional[Trip]:
        raise AssertionError("Unexpected invitation lookup")

    def find_by_participant(self, user_id: UserId) -> Sequence[Trip]:
        raise AssertionError("Unexpected membership query")

    def find_active_or_planned_trips_by_participant(
        self, user_id: UserId
    ) -> Sequence[Trip]:
        raise AssertionError("Unexpected overlap query")


class MemoryEpisodes:
    def __init__(self) -> None:
        self.stored: dict[EpisodeId, Episode] = {}
        self.saved: list[EpisodeId] = []
        self.deleted: list[EpisodeId] = []

    def delete(self, episode_id: EpisodeId) -> None:
        self.deleted.append(episode_id)
        if episode_id not in self.stored:
            raise LookupError("Episode not found during delete")
        del self.stored[episode_id]

    def get_by_id(self, episode_id: EpisodeId) -> Optional[Episode]:
        return deepcopy(self.stored.get(episode_id))

    def save(self, episode: Episode) -> Episode:
        self.stored[episode.id] = deepcopy(episode)
        self.saved.append(episode.id)
        return deepcopy(episode)

    def find_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        raise AssertionError("Unexpected episode listing")

    def find_unresolved_by_trip(self, trip_id: TripId) -> Sequence[Episode]:
        raise AssertionError("Unexpected unresolved query")


def active_trip(end=END):
    trip = Trip(
        TripId("trip"),
        "Holiday",
        AUTHOR,
        TripPeriod(START, end),
        InvitationCode("invite"),
    )
    request = trip.request_to_join(JoinRequestId("join"), PROTAGONIST)
    trip.approve_join_request(request.id, requested_by=AUTHOR)
    trip.activate(requested_by=AUTHOR, current_date=START)
    return trip


@pytest.fixture
def trips():
    return MemoryTrips(active_trip())


@pytest.fixture
def episodes():
    return MemoryEpisodes()


@pytest.fixture
def data():
    return dict(
        episode_id=EPISODE_ID,
        trip_id=TripId("trip"),
        author_id=AUTHOR,
        protagonist_id=PROTAGONIST,
        title="Wrong train",
        description="We took the wrong train",
        date=START,
    )


@pytest.fixture
def draft(episodes):
    episode = Episode(
        EPISODE_ID,
        TripId("trip"),
        AUTHOR,
        PROTAGONIST,
        "Wrong train",
        "We took the wrong train",
        START,
    )
    episodes.stored[episode.id] = deepcopy(episode)
    return episode


@pytest.fixture
def changes():
    return dict(
        title="Correct train",
        description="Updated details",
        date=END,
        protagonist_id=AUTHOR,
    )


def test_create_persists_draft_using_ports(data) -> None:
    trips = MemoryTrips(active_trip())
    episodes = MemoryEpisodes()
    trip_port: TripRepository = trips
    episode_port: EpisodeRepository = episodes
    before = deepcopy(vars(trips.stored[TripId("trip")]))
    result = CreateEpisode(trip_port, episode_port).execute(**data)
    assert result.status is EpisodeStatus.DRAFT
    assert result.author_id == AUTHOR
    assert result.protagonist_id == PROTAGONIST
    assert result.id == EPISODE_ID
    assert result.trip_id == data["trip_id"]
    assert result.title == data["title"]
    assert result.description == data["description"]
    assert result.date == data["date"]
    assert vars(episodes.stored[result.id]) == vars(result)
    assert episodes.saved == [result.id]
    assert trips.lookups == [data["trip_id"]]
    assert vars(trips.stored[data["trip_id"]]) == before


def test_create_allows_author_as_protagonist(trips, episodes, data):
    data["protagonist_id"] = AUTHOR
    result = CreateEpisode(trips, episodes).execute(**data)
    assert episodes.stored[result.id].protagonist_id == AUTHOR


def test_duplicate_episode_id_does_not_overwrite(trips, episodes, data, draft):
    before = deepcopy(vars(episodes.stored[draft.id]))
    with pytest.raises(EpisodeApplicationError, match="already"):
        CreateEpisode(trips, episodes).execute(**data)
    assert episodes.saved == []
    assert vars(episodes.stored[draft.id]) == before


@pytest.mark.parametrize("field", ["author_id", "protagonist_id"])
def test_create_rejects_nonparticipant(trips, episodes, data, field):
    data[field] = UserId("outsider")
    with pytest.raises(EpisodeApplicationError, match="participant"):
        CreateEpisode(trips, episodes).execute(**data)
    assert episodes.saved == []
    assert episodes.stored == {}


@pytest.mark.parametrize("day", [START, END])
def test_create_accepts_inclusive_boundaries(trips, episodes, data, day):
    data["date"] = day
    result = CreateEpisode(trips, episodes).execute(**data)
    assert episodes.stored[result.id].date == day


def test_create_accepts_single_day_trip(episodes, data):
    trips = MemoryTrips(active_trip(end=START))
    result = CreateEpisode(trips, episodes).execute(**data)
    assert episodes.stored[result.id].date == START


@pytest.mark.parametrize("mode", ["create", "edit"])
@pytest.mark.parametrize("day", [date(2026, 10, 31), date(2026, 11, 4)])
def test_date_outside_trip_is_rejected(trips, episodes, data, changes, mode, day):
    if mode == "edit":
        CreateEpisode(trips, episodes).execute(**data)
        episodes.saved.clear()
    before = {key: deepcopy(vars(value)) for key, value in episodes.stored.items()}
    with pytest.raises(EpisodeApplicationError, match="date"):
        if mode == "create":
            CreateEpisode(trips, episodes).execute(**{**data, "date": day})
        else:
            EditEpisode(trips, episodes).execute(
                episode_id=EPISODE_ID, requested_by=AUTHOR, **{**changes, "date": day}
            )
    assert episodes.saved == []
    assert {key: vars(value) for key, value in episodes.stored.items()} == before


def test_edit_persists_all_changes_and_preserves_identity(
    trips, episodes, draft, changes
):
    before = deepcopy(vars(trips.stored[draft.trip_id]))
    result = EditEpisode(trips, episodes).execute(
        episode_id=draft.id, requested_by=AUTHOR, **changes
    )
    assert (result.id, result.trip_id, result.author_id) == (
        draft.id,
        draft.trip_id,
        AUTHOR,
    )
    for key, value in changes.items():
        assert getattr(result, key) == value
    assert result.status is EpisodeStatus.DRAFT
    assert vars(episodes.stored[draft.id]) == vars(result)
    assert episodes.saved == [draft.id]
    assert trips.lookups == [draft.trip_id]
    assert vars(trips.stored[draft.trip_id]) == before


def test_edit_rejects_new_protagonist_outside_trip(trips, episodes, draft, changes):
    changes["protagonist_id"] = UserId("outsider")
    with pytest.raises(EpisodeApplicationError, match="participant"):
        EditEpisode(trips, episodes).execute(
            episode_id=draft.id, requested_by=AUTHOR, **changes
        )
    assert episodes.saved == []
    assert vars(episodes.stored[draft.id]) == vars(draft)


def test_submit_persists_voting_and_prevents_later_edit(
    trips, episodes, draft, changes
):
    result = SubmitEpisode(trips, episodes).execute(
        episode_id=draft.id, requested_by=AUTHOR
    )
    assert result.status is EpisodeStatus.VOTING
    assert vars(episodes.stored[draft.id]) == vars(result)
    assert episodes.saved == [draft.id]
    assert trips.lookups == [draft.trip_id]
    episodes.saved.clear()
    with pytest.raises(ValueError, match="DRAFT"):
        EditEpisode(trips, episodes).execute(
            episode_id=draft.id, requested_by=AUTHOR, **changes
        )
    assert episodes.saved == []
    assert vars(episodes.stored[draft.id]) == vars(result)


@pytest.mark.parametrize("mode", ["edit", "submit"])
def test_non_author_is_rejected_by_domain(trips, episodes, draft, changes, mode):
    with pytest.raises(ValueError, match="author"):
        if mode == "edit":
            EditEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=PROTAGONIST, **changes
            )
        else:
            SubmitEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=PROTAGONIST
            )
    assert episodes.saved == []
    assert vars(episodes.stored[draft.id]) == vars(draft)


@pytest.mark.parametrize("mode", ["edit", "submit"])
@pytest.mark.parametrize(
    "status", [EpisodeStatus.SUBMITTED, EpisodeStatus.VOTING, EpisodeStatus.COMPLETED]
)
def test_non_draft_is_rejected_by_domain(
    trips, episodes, draft, changes, mode, status, monkeypatch
):
    # Simulate loaded lifecycle states, including transient SUBMITTED, without voting setup.
    monkeypatch.setattr(episodes.stored[draft.id], "_status", status)
    before = deepcopy(vars(episodes.stored[draft.id]))
    with pytest.raises(ValueError, match="DRAFT"):
        if mode == "edit":
            EditEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=AUTHOR, **changes
            )
        else:
            SubmitEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=AUTHOR
            )
    assert episodes.saved == []
    assert vars(episodes.stored[draft.id]) == before


@pytest.mark.parametrize("mode", ["create", "edit", "submit"])
@pytest.mark.parametrize(
    "status", [TripStatus.PLANNED, TripStatus.COMPLETED, TripStatus.ARCHIVED]
)
def test_non_active_trip_is_rejected(
    trips, episodes, draft, data, changes, mode, status, monkeypatch
):
    monkeypatch.setattr(trips.stored[draft.trip_id], "_status", status)
    # Keep another ACTIVE trip to ensure edit/submit load the Episode's own Trip.
    other = active_trip()
    monkeypatch.setattr(other, "_id", TripId("other"))
    trips.stored[other.id] = other
    expected = ValueError if mode == "submit" else EpisodeApplicationError
    if mode == "create":
        episodes.stored.clear()
    with pytest.raises(expected, match="ACTIVE"):
        if mode == "create":
            CreateEpisode(trips, episodes).execute(**data)
        elif mode == "edit":
            EditEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=AUTHOR, **changes
            )
        else:
            SubmitEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=AUTHOR
            )
    assert episodes.saved == []
    assert trips.lookups == [draft.trip_id]


@pytest.mark.parametrize("mode", ["create", "edit", "submit"])
def test_missing_trip(trips, episodes, draft, data, changes, mode):
    trips.stored.clear()
    if mode == "create":
        episodes.stored.clear()
    with pytest.raises(LookupError, match="Trip"):
        if mode == "create":
            CreateEpisode(trips, episodes).execute(**data)
        elif mode == "edit":
            EditEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=AUTHOR, **changes
            )
        else:
            SubmitEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=AUTHOR
            )
    assert episodes.saved == []


@pytest.mark.parametrize("mode", ["edit", "submit"])
def test_missing_episode(trips, episodes, changes, mode):
    with pytest.raises(LookupError, match="Episode"):
        if mode == "edit":
            EditEpisode(trips, episodes).execute(
                episode_id=EPISODE_ID, requested_by=AUTHOR, **changes
            )
        else:
            SubmitEpisode(trips, episodes).execute(
                episode_id=EPISODE_ID, requested_by=AUTHOR
            )
    assert episodes.saved == []
    assert trips.lookups == []


@pytest.mark.parametrize("mode", ["create", "edit"])
def test_domain_field_validation_propagates(trips, episodes, data, changes, mode):
    if mode == "edit":
        CreateEpisode(trips, episodes).execute(**data)
        episodes.saved.clear()
    with pytest.raises(ValueError, match="title"):
        if mode == "create":
            CreateEpisode(trips, episodes).execute(**{**data, "title": ""})
        else:
            EditEpisode(trips, episodes).execute(
                episode_id=EPISODE_ID, requested_by=AUTHOR, **{**changes, "title": ""}
            )
    assert episodes.saved == []


@pytest.mark.parametrize("mode", ["create", "edit", "submit"])
@pytest.mark.parametrize("dependency", ["trip_lookup", "episode_lookup", "save"])
def test_technical_errors_propagate(
    trips, episodes, draft, data, changes, mode, dependency, monkeypatch
):
    if mode == "create":
        episodes.stored.clear()
    before = {key: deepcopy(vars(value)) for key, value in episodes.stored.items()}
    failure = RuntimeError("Repository unavailable")

    def fail(*args):
        raise failure

    target = trips if dependency == "trip_lookup" else episodes
    monkeypatch.setattr(target, "save" if dependency == "save" else "get_by_id", fail)
    with pytest.raises(RuntimeError) as error:
        if mode == "create":
            CreateEpisode(trips, episodes).execute(**data)
        elif mode == "edit":
            EditEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=AUTHOR, **changes
            )
        else:
            SubmitEpisode(trips, episodes).execute(
                episode_id=draft.id, requested_by=AUTHOR
            )
    assert error.value is failure
    assert episodes.saved == []
    assert {key: vars(value) for key, value in episodes.stored.items()} == before


def test_delete_removes_only_target_and_second_attempt_fails(trips, episodes, draft):
    other = Episode(
        EpisodeId("other"),
        draft.trip_id,
        AUTHOR,
        PROTAGONIST,
        "Other",
        "Description",
        START,
    )
    episodes.stored[other.id] = other
    trip_before = deepcopy(vars(trips.stored[draft.trip_id]))
    other_before = deepcopy(vars(other))
    use_case = DeleteEpisode(trips, episodes)
    assert use_case.execute(episode_id=draft.id, requested_by=AUTHOR) is None
    assert episodes.get_by_id(draft.id) is None
    assert set(episodes.stored) == {other.id}
    assert vars(episodes.stored[other.id]) == other_before
    assert episodes.deleted == [draft.id]
    assert episodes.saved == []
    assert trips.lookups == [draft.trip_id]
    assert vars(trips.stored[draft.trip_id]) == trip_before
    with pytest.raises(LookupError, match="Episode"):
        use_case.execute(episode_id=draft.id, requested_by=AUTHOR)
    assert episodes.deleted == [draft.id]


@pytest.mark.parametrize("missing", ["episode", "trip"])
def test_delete_missing_aggregate_does_not_write(trips, episodes, draft, missing):
    if missing == "episode":
        episodes.stored.clear()
    else:
        trips.stored.clear()
    with pytest.raises(LookupError):
        DeleteEpisode(trips, episodes).execute(episode_id=draft.id, requested_by=AUTHOR)
    assert episodes.deleted == []
    assert episodes.saved == []
    if missing == "episode":
        assert trips.lookups == []
    else:
        assert vars(episodes.stored[draft.id]) == vars(draft)


@pytest.mark.parametrize(
    "status", [TripStatus.PLANNED, TripStatus.COMPLETED, TripStatus.ARCHIVED]
)
def test_delete_checks_owning_trip_state(trips, episodes, draft, status, monkeypatch):
    # Reconstructed states follow the existing Episode use-case fixtures.
    monkeypatch.setattr(trips.stored[draft.trip_id], "_status", status)
    other = active_trip()
    monkeypatch.setattr(other, "_id", TripId("other"))
    trips.stored[other.id] = other
    before = deepcopy(vars(trips.stored[draft.trip_id]))
    with pytest.raises(EpisodeApplicationError, match="ACTIVE"):
        DeleteEpisode(trips, episodes).execute(episode_id=draft.id, requested_by=AUTHOR)
    assert trips.lookups == [draft.trip_id]
    assert episodes.deleted == []
    assert episodes.saved == []
    assert vars(episodes.stored[draft.id]) == vars(draft)
    assert vars(trips.stored[draft.trip_id]) == before


@pytest.mark.parametrize("actor", [AUTHOR, UserId("outsider")])
def test_delete_creator_has_no_privilege_over_another_authors_draft(
    trips, episodes, actor
):
    # AUTHOR is the actual Trip creator; PROTAGONIST is another Participant.
    episode = Episode(
        EPISODE_ID, TripId("trip"), PROTAGONIST, AUTHOR, "Title", "Description", START
    )
    episodes.stored[episode.id] = episode
    before = deepcopy(vars(episode))
    with pytest.raises(ValueError, match="author"):
        DeleteEpisode(trips, episodes).execute(
            episode_id=episode.id, requested_by=actor
        )
    assert vars(episode) == before
    assert episodes.deleted == []
    assert episodes.saved == []


@pytest.mark.parametrize(
    "status", [EpisodeStatus.SUBMITTED, EpisodeStatus.VOTING, EpisodeStatus.COMPLETED]
)
def test_delete_rejects_non_draft_without_write(
    trips, episodes, draft, status, monkeypatch
):
    # Same loaded-state fixture used by the existing edit/submit tests.
    monkeypatch.setattr(episodes.stored[draft.id], "_status", status)
    before = deepcopy(vars(episodes.stored[draft.id]))
    with pytest.raises(ValueError, match="DRAFT"):
        DeleteEpisode(trips, episodes).execute(episode_id=draft.id, requested_by=AUTHOR)
    assert vars(episodes.stored[draft.id]) == before
    assert episodes.deleted == []
    assert episodes.saved == []


@pytest.mark.parametrize("dependency", ["episode", "trip", "delete"])
def test_delete_propagates_technical_errors(
    trips, episodes, draft, dependency, monkeypatch
):
    error = RuntimeError("Storage unavailable")

    def fail(*args, **kwargs):
        raise error

    target = trips if dependency == "trip" else episodes
    monkeypatch.setattr(
        target, "delete" if dependency == "delete" else "get_by_id", fail
    )
    with pytest.raises(RuntimeError) as caught:
        DeleteEpisode(trips, episodes).execute(episode_id=draft.id, requested_by=AUTHOR)
    assert caught.value is error
    assert episodes.saved == []
    assert episodes.deleted == []
    assert vars(episodes.stored[draft.id]) == vars(draft)


def test_episode_disappearing_during_delete_propagates_lookup_error(
    trips, episodes, draft, monkeypatch
):
    original_delete = episodes.delete

    def disappear_then_delete(episode_id):
        del episodes.stored[episode_id]
        original_delete(episode_id)

    monkeypatch.setattr(episodes, "delete", disappear_then_delete)
    with pytest.raises(LookupError, match="during delete"):
        DeleteEpisode(trips, episodes).execute(episode_id=draft.id, requested_by=AUTHOR)
    assert episodes.deleted == [draft.id]
    assert episodes.saved == []
