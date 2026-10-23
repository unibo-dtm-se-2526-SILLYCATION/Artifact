"""Distinct domain identities, represented as immutable string values."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UserId:
    value: str


@dataclass(frozen=True)
class TripId:
    value: str


@dataclass(frozen=True)
class JoinRequestId:
    value: str


@dataclass(frozen=True)
class EpisodeId:
    value: str


@dataclass(frozen=True)
class VoteId:
    value: str
