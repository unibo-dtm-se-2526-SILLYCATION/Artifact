"""Connection ownership for standalone and unit-of-work repositories."""

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import Connection, Engine


class RepositoryContext:
    """Only standalone scopes own transactions; bound scopes never commit."""

    def __init__(self, engine: Engine, connection: Optional[Connection] = None) -> None:
        self._engine = engine
        self._connection = connection
        self._active = connection is not None
        self.failed = False

    def deactivate(self) -> None:
        self._active = False

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        if self._connection is None:
            with self._engine.connect() as connection:
                yield connection
        else:
            if not self._active:
                raise RuntimeError("Unit of work is no longer active")
            if self.failed:
                raise RuntimeError("Unit of work requires rollback")
            try:
                yield self._connection
            except BaseException:
                self.failed = True
                raise

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        if self._connection is None:
            with self._engine.begin() as connection:
                yield connection
        else:
            with self.connect() as connection:
                yield connection
