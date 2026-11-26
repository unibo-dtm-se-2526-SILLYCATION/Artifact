"""Database connection and schema initialisation."""

import os
from typing import Any, Optional

from sqlalchemy import Engine, create_engine, event

from sillycation.adapters.persistence.tables import metadata

DATABASE_URL_VARIABLE = "SILLYCATION_DATABASE_URL"
DEFAULT_DATABASE_URL = "sqlite:///sillycation.db"


def resolve_database_url(url: Optional[str] = None) -> str:
    return (
        os.environ.get(DATABASE_URL_VARIABLE, DEFAULT_DATABASE_URL)
        if url is None
        else url
    )


def _enable_sqlite_foreign_keys(connection: Any, connection_record: Any) -> None:
    """Configure each physical connection before schema creation or SQL use."""
    has_autocommit = hasattr(connection, "autocommit")
    previous_autocommit = connection.autocommit if has_autocommit else None
    if has_autocommit:
        connection.autocommit = True
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
    finally:
        if has_autocommit:
            connection.autocommit = previous_autocommit


def create_database(url: Optional[str] = None) -> Engine:
    """Connect to the database and create any missing table.

    The URL comes from the argument, otherwise from the environment variable
    SILLYCATION_DATABASE_URL, otherwise it is a local SQLite file. Existing
    tables and their data are left untouched, so this is safe at every start.
    """
    engine = create_engine(resolve_database_url(url))
    try:
        if engine.dialect.name == "sqlite":
            event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        metadata.create_all(engine)
    except BaseException:
        engine.dispose()
        raise
    return engine
