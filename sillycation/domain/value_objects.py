"""Basic domain values and their local invariants."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TripPeriod:
    """A closed date interval, including both boundary dates (INV-03)."""

    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("Trip start date must not be later than end date")

    def overlaps(self, other: "TripPeriod") -> bool:
        return self.start_date <= other.end_date and self.end_date >= other.start_date


@dataclass(frozen=True)
class InvitationCode:
    """Invitation text; generation and uniqueness belong to trip creation."""

    value: str


@dataclass(frozen=True)
class VoteValue:
    """An integer rating between 1 and 5 inclusive (INV-12)."""

    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or not 1 <= self.value <= 5:
            raise ValueError("Vote value must be an integer between 1 and 5")
