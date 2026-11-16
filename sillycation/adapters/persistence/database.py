"""Database connection and schema initialisation."""

import os
from typing import Optional

from sqlalchemy import Engine, create_engine

from sillycation.adapters.persistence.tables import metadata

DATABASE_URL_VARIABLE = "SILLYCATION_DATABASE_URL"
DEFAULT_DATABASE_URL = "sqlite:///sillycation.db"


def create_database(url: Optional[str] = None) -> Engine:
    """Connect to the database and create any missing table.

    The URL comes from the argument, otherwise from the environment variable
    SILLYCATION_DATABASE_URL, otherwise it is a local SQLite file. Existing
    tables and their data are left untouched, so this is safe at every start.
    """
    if url is None:
        url = os.environ.get(DATABASE_URL_VARIABLE, DEFAULT_DATABASE_URL)
    engine = create_engine(url)
    metadata.create_all(engine)
    return engine
