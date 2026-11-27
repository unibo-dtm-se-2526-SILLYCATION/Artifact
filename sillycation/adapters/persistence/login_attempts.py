"""SQLite-backed login budgets shared by processes using the same database."""

from math import ceil
from typing import Callable, Optional, cast

from sqlalchemy import Column, Engine, Integer, MetaData, String, Table, delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.schema import CreateTable


attempts = Table(
    "login_attempts",
    MetaData(),
    Column("scope", String, primary_key=True),
    Column("window", Integer, nullable=False),
    Column("count", Integer, nullable=False),
)


class SqliteLoginAttempts:
    WINDOW_SECONDS = 60
    PEER_LIMIT = 10
    TOTAL_LIMIT = 120

    def __init__(self, engine: Engine, clock: Callable[[], float]) -> None:
        self._engine = engine
        self._clock = clock
        with engine.begin() as connection:
            connection.execute(CreateTable(attempts, if_not_exists=True))

    def consume(self, peer: str) -> Optional[int]:
        """Reserve an attempt before verification, or return seconds until reset."""
        with self._engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            now = self._clock()
            window = int(now) // self.WINDOW_SECONDS
            connection.execute(delete(attempts).where(attempts.c.window != window))
            budgets = {"total": self.TOTAL_LIMIT, f"peer:{peer}": self.PEER_LIMIT}
            rows = connection.execute(
                select(attempts.c.scope, attempts.c.count).where(
                    attempts.c.scope.in_(budgets)
                )
            )
            counts = {cast(str, scope): cast(int, count) for scope, count in rows}
            if any(counts.get(scope, 0) >= limit for scope, limit in budgets.items()):
                return ceil((window + 1) * self.WINDOW_SECONDS - now)

            connection.execute(
                insert(attempts)
                .values(
                    [
                        {"scope": scope, "window": window, "count": 1}
                        for scope in budgets
                    ]
                )
                .on_conflict_do_update(
                    index_elements=[attempts.c.scope],
                    set_={"count": attempts.c.count + 1},
                )
            )
        return None
