"""Transaction boundary independent of database technology.

A fresh unit is single-use. Repositories are available only inside its active
context and share one transaction. Commit is explicit; exiting without commit
rolls back. Failed persistence operations must prevent commit even if caught.
Neither exit nor rollback suppresses the original operation's exception.
"""

from types import TracebackType
from typing import Optional, Protocol

from sillycation.application.ports.repositories import (
    EpisodeRepository,
    TripRepository,
    UserRepository,
)


class UnitOfWork(Protocol):
    @property
    def users(self) -> UserRepository: ...

    @property
    def trips(self) -> TripRepository: ...

    @property
    def episodes(self) -> EpisodeRepository: ...

    def __enter__(self) -> "UnitOfWork": ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None: ...
