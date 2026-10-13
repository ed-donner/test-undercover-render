"""Counting what the backend has recorded, straight from its tables."""

from sqlalchemy import Table, func, select

from backend.database import engine


def count(table: Table) -> int:
    """How many rows a table holds."""
    with engine().connect() as db:
        return db.execute(select(func.count()).select_from(table)).scalar_one()
