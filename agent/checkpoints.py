"""The checkpoints, where the agent's graphs save their progress: the process's pool
of connections to DATABASE_URL, with LangGraph's PostgresSaver set up in our own
schema."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection, sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

Pool = ConnectionPool[Connection[DictRow]]

SCHEMA = "undercover"
CONNECTIONS = 4
CONNECTION_WAIT = 120
# How long the pool waits for its first connection as it opens, so an agent that
# can't reach the database says so well inside the app's 10-second call.
OPEN_WAIT = 5


def open_checkpoint_pool() -> Pool:
    """Open the process's pool of at most CONNECTIONS connections to DATABASE_URL,
    where graphs save their progress in our own schema, set up once. It waits up to
    OPEN_WAIT seconds for its first connection, and a graph up to CONNECTION_WAIT
    seconds for one. Prepared statements are off, so it works through either of
    Supabase's poolers."""
    settings = {
        "autocommit": True,
        "prepare_threshold": None,
        "row_factory": dict_row,
        "options": f"-c search_path={SCHEMA}",
    }
    pool = ConnectionPool[Connection[DictRow]](
        os.environ["DATABASE_URL"],
        min_size=1,
        max_size=CONNECTIONS,
        timeout=CONNECTION_WAIT,
        kwargs=settings,
        open=True,
    )
    try:
        pool.wait(timeout=OPEN_WAIT)
        with pool.connection() as connection:
            create = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")
            connection.execute(create.format(sql.Identifier(SCHEMA)))
        PostgresSaver(pool).setup()
    except Exception:  # a pool that can't be set up is closed, to be opened again
        pool.close()
        raise
    return pool


@contextmanager
def checkpoint_pool() -> Iterator[Pool]:
    """The process's checkpoint pool, open while the block runs."""
    with open_checkpoint_pool() as pool:
        yield pool
