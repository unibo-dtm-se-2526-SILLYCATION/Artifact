from concurrent.futures import ThreadPoolExecutor

from sillycation.adapters.persistence.database import create_database
from sillycation.adapters.persistence.login_attempts import SqliteLoginAttempts


def test_concurrent_workers_share_a_peer_budget(database_url) -> None:
    first = create_database(database_url)
    second = create_database(database_url)
    try:
        limiters = [
            SqliteLoginAttempts(engine, lambda: 600.0) for engine in (first, second)
        ]

        def attempt(index: int):
            return limiters[index % 2].consume("192.0.2.1")

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(16)))
        assert results.count(None) == 10
        assert results.count(60) == 6
        assert limiters[1].consume("192.0.2.2") is None
    finally:
        first.dispose()
        second.dispose()


def test_rotating_peers_cannot_exceed_total_budget(engine) -> None:
    now = 600.0
    limiter = SqliteLoginAttempts(engine, lambda: now)
    for peer in range(120):
        assert limiter.consume(f"peer-{peer}") is None
    assert limiter.consume("new-peer") == 60
    now += 60
    assert limiter.consume("new-peer") is None
