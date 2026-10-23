from dataclasses import FrozenInstanceError
from itertools import combinations

import pytest

from sillycation.domain.identifiers import (
    EpisodeId,
    JoinRequestId,
    TripId,
    UserId,
    VoteId,
)


IDENTIFIER_TYPES = (UserId, TripId, JoinRequestId, EpisodeId, VoteId)


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES)
def test_identifiers_compare_by_value(identifier_type):
    identifier = identifier_type("id-1")
    assert identifier.value == "id-1"
    assert identifier == identifier_type("id-1")
    assert identifier != identifier_type("id-2")
    assert identifier != "id-1"


@pytest.mark.parametrize("left,right", list(combinations(IDENTIFIER_TYPES, 2)))
def test_identifier_types_are_distinct(left, right):
    assert left("same-id") != right("same-id")


@pytest.mark.parametrize("identifier_type", IDENTIFIER_TYPES)
def test_identifiers_are_immutable(identifier_type):
    identifier = identifier_type("id-1")
    with pytest.raises(FrozenInstanceError):
        identifier.value = "id-2"
