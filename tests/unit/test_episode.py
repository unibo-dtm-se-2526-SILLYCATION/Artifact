from datetime import date

import pytest

from sillycation.domain.episode import Episode, EpisodeStatus
from sillycation.domain.identifiers import EpisodeId, TripId, UserId
from sillycation.domain.trip import TripStatus


AUTHOR = UserId("author")
PROTAGONIST = UserId("protagonist")
DAY = date(2026, 10, 25)


@pytest.fixture
def data():
    # Trip membership, ACTIVE status and date interval are checked by the caller.
    return dict(
        id=EpisodeId("episode"),
        trip_id=TripId("trip"),
        author_id=AUTHOR,
        protagonist_id=PROTAGONIST,
        title="Wrong train",
        description="We boarded the wrong train.",
        date=DAY,
    )


@pytest.fixture
def episode(data):
    return Episode(**data)


def test_creation_preserves_fields_and_starts_draft(episode, data):
    for field, value in data.items():
        assert getattr(episode, field) == value
    assert episode.status is EpisodeStatus.DRAFT


def test_author_can_also_be_protagonist(data):
    data["protagonist_id"] = AUTHOR
    assert Episode(**data).protagonist_id == AUTHOR


@pytest.mark.parametrize("field", ["title", "description"])
@pytest.mark.parametrize("value", [None, "", " \t\n"])
def test_mandatory_text_cannot_be_missing_or_blank(data, field, value):
    data[field] = value
    with pytest.raises(ValueError):
        Episode(**data)


def test_text_is_preserved_without_undocumented_length_limits(data):
    data["title"] = "  " + "Title" * 1000 + "  "
    data["description"] = "  Description\n" * 1000
    episode = Episode(**data)
    assert episode.title == data["title"]
    assert episode.description == data["description"]


@pytest.mark.parametrize(
    "field", ["id", "trip_id", "author_id", "protagonist_id", "date"]
)
def test_mandatory_identity_and_date_cannot_be_missing(data, field):
    data[field] = None
    with pytest.raises(ValueError):
        Episode(**data)


def test_author_can_edit_draft(episode):
    episode.edit(
        requested_by=AUTHOR,
        title="Correct train",
        description="New details",
        date=DAY,
        protagonist_id=AUTHOR,
    )
    assert episode.title == "Correct train"
    assert episode.description == "New details"
    assert episode.date == DAY
    assert episode.protagonist_id == AUTHOR
    assert episode.author_id == AUTHOR
    assert episode.status is EpisodeStatus.DRAFT


def test_non_author_cannot_edit_draft(episode, data):
    with pytest.raises(ValueError):
        episode.edit(
            requested_by=PROTAGONIST,
            title="Changed",
            description="Changed",
            date=DAY,
            protagonist_id=AUTHOR,
        )
    for field, value in data.items():
        assert getattr(episode, field) == value


@pytest.mark.parametrize(
    "field,value",
    [("title", ""), ("description", ""), ("date", None), ("protagonist_id", None)],
)
def test_failed_edit_preserves_all_fields(episode, data, field, value):
    changes = dict(
        title="Changed", description="Changed", date=DAY, protagonist_id=AUTHOR
    )
    changes[field] = value
    with pytest.raises(ValueError):
        episode.edit(requested_by=AUTHOR, **changes)
    for field, value in data.items():
        assert getattr(episode, field) == value


def test_submission_automatically_opens_voting(episode, data):
    episode.submit(requested_by=AUTHOR, trip_status=TripStatus.ACTIVE)
    assert episode.status is EpisodeStatus.VOTING
    for field, value in data.items():
        assert getattr(episode, field) == value


@pytest.mark.parametrize("actor", [PROTAGONIST, UserId("outsider")])
def test_only_author_can_submit(episode, actor):
    with pytest.raises(ValueError):
        episode.submit(requested_by=actor, trip_status=TripStatus.ACTIVE)
    assert episode.status is EpisodeStatus.DRAFT


@pytest.mark.parametrize(
    "status", [TripStatus.PLANNED, TripStatus.COMPLETED, TripStatus.ARCHIVED]
)
def test_submission_requires_current_active_trip(episode, status):
    with pytest.raises(ValueError):
        episode.submit(requested_by=AUTHOR, trip_status=status)
    assert episode.status is EpisodeStatus.DRAFT


def test_episode_cannot_be_submitted_twice(episode):
    episode.submit(requested_by=AUTHOR, trip_status=TripStatus.ACTIVE)
    with pytest.raises(ValueError):
        episode.submit(requested_by=AUTHOR, trip_status=TripStatus.ACTIVE)
    assert episode.status is EpisodeStatus.VOTING


def test_submitted_episode_cannot_be_edited(episode, data):
    episode.submit(requested_by=AUTHOR, trip_status=TripStatus.ACTIVE)
    with pytest.raises(ValueError):
        episode.edit(
            requested_by=AUTHOR,
            title="Changed",
            description="Changed",
            date=DAY,
            protagonist_id=AUTHOR,
        )
    for field, value in data.items():
        assert getattr(episode, field) == value


@pytest.mark.parametrize("submitted", [False, True])
@pytest.mark.parametrize(
    "field,value",
    [
        ("id", EpisodeId("other")),
        ("trip_id", TripId("other")),
        ("author_id", PROTAGONIST),
        ("protagonist_id", AUTHOR),
        ("title", "Changed"),
        ("description", "Changed"),
        ("date", DAY),
        ("status", EpisodeStatus.DRAFT),
        ("status", EpisodeStatus.SUBMITTED),
        ("status", EpisodeStatus.VOTING),
        ("status", EpisodeStatus.COMPLETED),
    ],
)
def test_public_properties_cannot_bypass_domain_operations(
    episode, submitted, field, value
):
    if submitted:
        episode.submit(requested_by=AUTHOR, trip_status=TripStatus.ACTIVE)
    with pytest.raises(AttributeError):
        setattr(episode, field, value)
