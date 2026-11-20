"""Real file-backed SQLite transactions; no command executor is wired here."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event, get_ident
from unittest.mock import Mock

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.exc import IntegrityError, OperationalError

from sillycation.adapters.persistence.tables import episodes, trips, users
from sillycation.adapters.persistence.unit_of_work import SqliteUnitOfWork
from sillycation.adapters.persistence.user_repository import SqlAlchemyUserRepository
from sillycation.application.ports.unit_of_work import UnitOfWork
from sillycation.domain.episode import Episode
from sillycation.domain.identifiers import EpisodeId, TripId, UserId
from sillycation.domain.trip import Trip
from sillycation.domain.user import User
from sillycation.domain.value_objects import InvitationCode, TripPeriod

DAY = date(2026, 11, 10)
ANNA = User(UserId("anna"), "Anna", "anna@example.org", "hash")
BOB = User(UserId("bob"), "Bob", "bob@example.org", "hash-bob")


def rows(engine, table):
    with engine.connect() as connection:
        return connection.execute(select(table)).all()


def test_repositories_share_connection_and_wait_for_explicit_commit(
    engine: Engine,
) -> None:
    statements = []
    commits = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append((id(connection), statement))

    event.listen(engine, "before_cursor_execute", record)
    event.listen(engine, "commit", lambda connection: commits.append(connection))
    unit: UnitOfWork = SqliteUnitOfWork(engine)
    with unit as transaction:
        transaction.users.save(ANNA)
        trip = Trip(
            TripId("trip"),
            "Holiday",
            ANNA.id,
            TripPeriod(DAY, DAY),
            InvitationCode("CODE"),
        )
        transaction.trips.save(trip)
        episode = Episode(
            EpisodeId("episode"), trip.id, ANNA.id, ANNA.id, "Title", "Details", DAY
        )
        transaction.episodes.save(episode)
        assert transaction.users.get_by_id(ANNA.id) is not None
        assert transaction.trips.get_by_id(trip.id) is not None
        assert transaction.episodes.get_by_id(episode.id) is not None
        # Only repository statements have run so far, on one SQLAlchemy connection.
        assert len({identity for identity, _ in statements}) == 1
        sql = [statement for _, statement in statements]
        begin = sql.index("BEGIN IMMEDIATE")
        assert all(statement.startswith("PRAGMA") for statement in sql[:begin])
        assert any(statement.startswith("SELECT") for statement in sql[begin + 1 :])
        assert commits == []
        # A second physical connection cannot observe uncommitted repository writes.
        for table in (users, trips, episodes):
            assert rows(engine, table) == []
        transaction.commit()
        assert len(commits) == 1
    assert (
        len(rows(engine, users))
        == len(rows(engine, trips))
        == len(rows(engine, episodes))
        == 1
    )
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


@pytest.mark.parametrize("explicit", [False, True])
def test_no_commit_and_explicit_rollback_both_discard_writes(
    engine: Engine, explicit
) -> None:
    with SqliteUnitOfWork(engine) as unit:
        unit.users.save(ANNA)
        if explicit:
            unit.rollback()
    assert rows(engine, users) == []
    with SqliteUnitOfWork(engine) as following:
        following.users.save(BOB)
        following.commit()
    assert SqlAlchemyUserRepository(engine).get_by_id(BOB.id) is not None


def test_operation_exception_is_not_suppressed_and_rolls_back(engine: Engine) -> None:
    error = ValueError("application failure")
    with pytest.raises(ValueError) as caught:
        with SqliteUnitOfWork(engine) as unit:
            unit.users.save(ANNA)
            raise error
    assert caught.value is error
    assert rows(engine, users) == []


def test_caught_foreign_key_error_poisoned_entire_unit(engine: Engine) -> None:
    with SqliteUnitOfWork(engine) as unit:
        unit.users.save(ANNA)
        trip = Trip(
            TripId("bad"),
            "Bad",
            UserId("missing"),
            TripPeriod(DAY, DAY),
            InvitationCode("BAD"),
        )
        with pytest.raises(IntegrityError):
            unit.trips.save(trip)
        with pytest.raises(RuntimeError, match="failed"):
            unit.commit()
        with pytest.raises(RuntimeError, match="rollback"):
            unit.users.get_by_id(ANNA.id)
        unit.rollback()
    assert rows(engine, users) == rows(engine, trips) == []


def test_failed_episode_write_rolls_back_other_repositories(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with SqliteUnitOfWork(engine) as unit:
            unit.users.save(ANNA)
            trip = Trip(
                TripId("trip"),
                "Holiday",
                ANNA.id,
                TripPeriod(DAY, DAY),
                InvitationCode("CODE"),
            )
            unit.trips.save(trip)
            episode = Episode(
                EpisodeId("bad"),
                trip.id,
                ANNA.id,
                UserId("missing"),
                "Title",
                "Details",
                DAY,
            )
            unit.episodes.save(episode)
            pytest.fail("An invalid episode must not be accepted")
    assert rows(engine, users) == rows(engine, trips) == rows(engine, episodes) == []


@pytest.mark.parametrize("method", ["commit", "rollback"])
def test_transaction_operations_require_active_context(engine: Engine, method) -> None:
    unit = SqliteUnitOfWork(engine)
    with pytest.raises(RuntimeError, match="not active"):
        getattr(unit, method)()
    with unit:
        getattr(unit, method)()
        with pytest.raises(RuntimeError, match="not active"):
            getattr(unit, method)()


@pytest.mark.parametrize("repository", ["users", "trips", "episodes"])
def test_repository_properties_require_active_context(
    engine: Engine, repository
) -> None:
    unit = SqliteUnitOfWork(engine)
    with pytest.raises(RuntimeError, match="not active"):
        getattr(unit, repository)
    with unit:
        assert getattr(unit, repository) is not None
    with pytest.raises(RuntimeError, match="not active"):
        getattr(unit, repository)


@pytest.mark.parametrize("finish", ["commit", "rollback", "exit"])
def test_retained_repositories_cannot_escape_transaction(
    engine: Engine, finish
) -> None:
    with SqliteUnitOfWork(engine) as unit:
        user_repository, trip_repository, episode_repository = (
            unit.users,
            unit.trips,
            unit.episodes,
        )
        if finish != "exit":
            getattr(unit, finish)()
            with pytest.raises(RuntimeError, match="no longer active"):
                user_repository.save(ANNA)
    with pytest.raises(RuntimeError, match="no longer active"):
        user_repository.get_by_id(ANNA.id)
    with pytest.raises(RuntimeError, match="no longer active"):
        trip_repository.get_by_id(TripId("trip"))
    with pytest.raises(RuntimeError, match="no longer active"):
        episode_repository.get_by_id(EpisodeId("episode"))
    assert rows(engine, users) == []


def test_nested_and_reused_units_are_rejected(engine: Engine) -> None:
    unit = SqliteUnitOfWork(engine)
    with unit:
        with pytest.raises(RuntimeError, match="nested"):
            with unit:
                pytest.fail("Nested reuse must not enter")
        with pytest.raises(RuntimeError, match="Nested"):
            with SqliteUnitOfWork(engine):
                pytest.fail("Nested transaction must not enter")
    with pytest.raises(RuntimeError, match="reused"):
        with unit:
            pytest.fail("A closed unit is single-use")
    with SqliteUnitOfWork(engine):
        pass


def test_failed_commit_propagates_and_discards_writes(engine: Engine) -> None:
    error = RuntimeError("commit failure")

    def fail(connection):
        raise error

    event.listen(engine, "commit", fail)
    try:
        with pytest.raises(RuntimeError) as caught:
            with SqliteUnitOfWork(engine) as unit:
                unit.users.save(ANNA)
                unit.commit()
        assert caught.value is error
    finally:
        event.remove(engine, "commit", fail)
    assert rows(engine, users) == []
    with SqliteUnitOfWork(engine) as following:
        following.users.save(BOB)
        following.commit()
    assert SqlAlchemyUserRepository(engine).get_by_id(BOB.id) is not None


def test_failed_begin_releases_connection_and_unit_cannot_be_reused(
    engine: Engine,
) -> None:
    error = OperationalError("BEGIN IMMEDIATE", {}, RuntimeError("driver failure"))

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE":
            raise error

    event.listen(engine, "before_cursor_execute", fail)
    unit = SqliteUnitOfWork(engine)
    try:
        with pytest.raises(OperationalError) as caught:
            with unit:
                pytest.fail("A failed begin must not enter")
        assert caught.value is error
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    with pytest.raises(RuntimeError, match="reused"):
        with unit:
            pytest.fail("A failed unit is single-use")
    with SqliteUnitOfWork(engine) as following:
        following.users.save(BOB)
        following.commit()
    assert SqlAlchemyUserRepository(engine).get_by_id(BOB.id) is not None


def test_writer_timeout_is_real_and_does_not_leak_writes_or_locks(
    engine: Engine,
) -> None:
    with engine.connect() as connection:
        original_timeout = connection.exec_driver_sql(
            "PRAGMA busy_timeout"
        ).scalar_one()

    def contend():
        with SqliteUnitOfWork(engine, timeout=0.02) as second:
            second.users.save(BOB)
            second.commit()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with SqliteUnitOfWork(engine) as first:
            first.users.save(ANNA)
            future = pool.submit(contend)
            with pytest.raises(OperationalError, match="locked"):
                future.result(timeout=5)
            first.commit()
    assert SqlAlchemyUserRepository(engine).get_by_id(ANNA.id) is not None
    assert SqlAlchemyUserRepository(engine).get_by_id(BOB.id) is None
    with SqliteUnitOfWork(engine, timeout=0.02) as following:
        following.users.save(BOB)
        following.commit()
    assert SqlAlchemyUserRepository(engine).get_by_id(BOB.id) is not None
    # Every pooled connection restores the busy timeout it had before the unit.
    with engine.connect() as first_connection, engine.connect() as second_connection:
        for connection in (first_connection, second_connection):
            assert (
                connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
                == original_timeout
            )


@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan"), 1e10])
def test_timeout_must_fit_sqlite_milliseconds(engine: Engine, timeout) -> None:
    with pytest.raises(ValueError):
        SqliteUnitOfWork(engine, timeout=timeout)


def test_non_sqlite_engine_is_rejected_without_connecting() -> None:
    engine = Mock(spec=Engine)
    engine.dialect = Mock(name="dialect")
    engine.dialect.name = "postgresql"
    with pytest.raises(ValueError, match="SQLite"):
        SqliteUnitOfWork(engine)
    engine.connect.assert_not_called()


def test_waiting_writer_reads_committed_data_after_acquiring_lock(
    engine: Engine,
) -> None:
    attempted = Event()
    read = Event()
    main_thread = get_ident()

    def record(connection, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE" and get_ident() != main_thread:
            attempted.set()

    def second_operation():
        with SqliteUnitOfWork(engine, timeout=2) as unit:
            loaded = unit.users.get_by_id(ANNA.id)
            read.set()
            assert loaded is not None
            unit.users.save(BOB)
            unit.commit()
        return loaded.id

    event.listen(engine, "before_cursor_execute", record)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with SqliteUnitOfWork(engine) as first:
                first.users.save(ANNA)
                future = pool.submit(second_operation)
                assert attempted.wait(timeout=5)
                assert not read.is_set()
                first.commit()
            assert future.result(timeout=5) == ANNA.id
        assert read.is_set()
        assert SqlAlchemyUserRepository(engine).get_by_id(BOB.id) is not None
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_cleanup_failure_preserves_original_exception_and_releases_context(
    engine: Engine,
) -> None:
    original = ValueError("application error")
    cleanup = RuntimeError("cleanup error")
    fail_cleanup = False
    with engine.connect() as connection:
        previous = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()

    def fail(connection, cursor, statement, parameters, context, executemany):
        if fail_cleanup and statement == f"PRAGMA busy_timeout={previous}":
            raise cleanup

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(ValueError) as caught:
            with SqliteUnitOfWork(engine, timeout=0.02) as unit:
                unit.users.save(ANNA)
                fail_cleanup = True
                raise original
        assert caught.value is original
        assert caught.value.__cause__ is cleanup
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert rows(engine, users) == []
    with SqliteUnitOfWork(engine) as following:
        following.users.save(BOB)
        following.commit()
    assert SqlAlchemyUserRepository(engine).get_by_id(BOB.id) is not None
