from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from sillycation.domain.value_objects import InvitationCode, TripPeriod, VoteValue


def day(number):
    return date(2026, 10, number)


@pytest.mark.parametrize("start,end", [(1, 5), (1, 1)])
def test_valid_trip_period(start, end):
    period = TripPeriod(day(start), day(end))
    assert period.start_date == day(start)
    assert period.end_date == day(end)
    assert period == TripPeriod(day(start), day(end))


def test_reversed_trip_period_is_rejected():
    with pytest.raises(ValueError):
        TripPeriod(day(5), day(1))


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (1, 2, False),  # strictly before
        (8, 9, False),  # strictly after
        (1, 3, True),  # shared start boundary
        (7, 9, True),  # shared end boundary
        (2, 4, True),  # partial overlap
        (6, 8, True),
        (4, 6, True),  # contained
        (1, 9, True),  # containing
        (3, 7, True),  # identical
        (3, 3, True),  # single day on boundary
        (7, 7, True),
        (5, 5, True),  # single day inside
    ],
)
def test_overlap_is_inclusive_and_symmetric(start, end, expected):
    period = TripPeriod(day(3), day(7))
    other = TripPeriod(day(start), day(end))
    assert period.overlaps(other) is expected
    assert other.overlaps(period) is expected


def test_single_day_period_overlaps_itself():
    period = TripPeriod(day(3), day(3))
    assert period.overlaps(period)
    assert not period.overlaps(TripPeriod(day(4), day(4)))


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5])
def test_valid_vote_value(value):
    vote = VoteValue(value)
    assert vote.value == value
    assert vote == VoteValue(value)


@pytest.mark.parametrize("value", [-1, 0, 6, 100, 2.5, 1.0, "3", True, False, None])
def test_invalid_vote_value_is_rejected(value):
    with pytest.raises(ValueError):
        VoteValue(value)


def test_different_vote_values_are_not_equal():
    assert VoteValue(1) != VoteValue(5)


def test_invitation_code_preserves_value_and_compares_by_value():
    code = InvitationCode("Trip-2026")
    assert code.value == "Trip-2026"
    assert code == InvitationCode("Trip-2026")
    assert code != InvitationCode("Trip-2027")


@pytest.mark.parametrize(
    "instance,attribute,replacement",
    [
        (TripPeriod(day(1), day(5)), "start_date", day(2)),
        (TripPeriod(day(1), day(5)), "end_date", day(6)),
        (InvitationCode("Trip-2026"), "value", "Trip-2027"),
        (VoteValue(1), "value", 5),
    ],
)
def test_value_objects_are_immutable(instance, attribute, replacement):
    with pytest.raises(FrozenInstanceError):
        setattr(instance, attribute, replacement)
