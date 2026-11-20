"""Single-use SQLite write transaction, not yet wired to application commands.

BEGIN IMMEDIATE precedes all repository reads. No retry is performed. Each unit
owns a connection and its repositories; commit/rollback ends their usable life.
Existing standalone repositories retain their per-operation transactions and
must not be mistaken for this whole-operation concurrency boundary.
"""

from contextvars import ContextVar, Token
from math import isfinite
from types import TracebackType
from typing import Optional

from sqlalchemy import Connection, Engine

from sillycation.adapters.persistence._connection import RepositoryContext
from sillycation.adapters.persistence.episode_repository import (
    SqlAlchemyEpisodeRepository,
)
from sillycation.adapters.persistence.trip_repository import SqlAlchemyTripRepository
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository

_active_engines: ContextVar[tuple[Engine, ...]] = ContextVar(
    "active_sqlite_units", default=()
)


class SqliteUnitOfWork:
    def __init__(self, engine: Engine, *, timeout: float = 5.0) -> None:
        if engine.dialect.name != "sqlite":
            raise ValueError("SqliteUnitOfWork requires a SQLite engine")
        if not isfinite(timeout) or not 0 <= timeout <= 2_147_483_647 / 1000:
            raise ValueError("Timeout must be finite and non-negative")
        self._engine = engine
        self._timeout_ms = int(timeout * 1000)
        self._connection: Optional[Connection] = None
        self._scope: Optional[RepositoryContext] = None
        self._previous_timeout: Optional[int] = None
        self._token: Optional[Token] = None
        self._entered = False
        self._finished = False

    def __enter__(self) -> "SqliteUnitOfWork":
        if self._entered:
            raise RuntimeError("Unit of work cannot be nested or reused")
        if self._engine in _active_engines.get():
            raise RuntimeError("Nested units for the same engine are not supported")
        self._entered = True
        try:
            connection = self._engine.connect()
            self._connection = connection
            self._previous_timeout = connection.exec_driver_sql(
                "PRAGMA busy_timeout"
            ).scalar_one()
            connection.exec_driver_sql(f"PRAGMA busy_timeout={self._timeout_ms}")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            self._scope = RepositoryContext(self._engine, connection)
            self._users = SqlAlchemyUserRepository(self._engine, _context=self._scope)
            self._trips = SqlAlchemyTripRepository(self._engine, _context=self._scope)
            self._episodes = SqlAlchemyEpisodeRepository(
                self._engine, _context=self._scope
            )
            self._token = _active_engines.set((*_active_engines.get(), self._engine))
        except BaseException as error:
            try:
                self._close()
            except BaseException as cleanup_error:
                raise error from cleanup_error
            raise
        return self

    def _active_scope(self) -> RepositoryContext:
        if self._scope is None or self._finished:
            raise RuntimeError("Unit of work is not active")
        return self._scope

    @property
    def users(self) -> SqlAlchemyUserRepository:
        self._active_scope()
        return self._users

    @property
    def trips(self) -> SqlAlchemyTripRepository:
        self._active_scope()
        return self._trips

    @property
    def episodes(self) -> SqlAlchemyEpisodeRepository:
        self._active_scope()
        return self._episodes

    def commit(self) -> None:
        scope = self._active_scope()
        if scope.failed:
            raise RuntimeError("Cannot commit a failed unit of work")
        assert self._connection is not None
        try:
            self._connection.commit()
        except BaseException:
            scope.failed = True
            raise
        self._finished = True
        scope.deactivate()

    def rollback(self) -> None:
        scope = self._active_scope()
        assert self._connection is not None
        try:
            self._connection.rollback()
        finally:
            self._finished = True
            scope.deactivate()

    def _close(self) -> None:
        if self._scope is not None:
            self._scope.deactivate()
        self._finished = True
        try:
            if self._connection is not None:
                try:
                    self._connection.rollback()
                    if self._previous_timeout is not None:
                        self._connection.exec_driver_sql(
                            f"PRAGMA busy_timeout={self._previous_timeout}"
                        )
                except BaseException:
                    # Never return a broken or incompletely restored connection
                    # to the pool, even when preserving an earlier exception.
                    self._connection.invalidate()
                    raise
                finally:
                    self._connection.close()
        finally:
            self._connection = None
            if self._token is not None:
                _active_engines.reset(self._token)
                self._token = None

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        try:
            self._close()
        except BaseException as cleanup_error:
            if exc is not None:
                raise exc.with_traceback(traceback) from cleanup_error
            raise
