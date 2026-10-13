import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, Text, inspect
from sqlalchemy.pool import QueuePool

from backend.database import RETIRED, engine, location, seed
from backend.main import app
from backend.tests.dashboard_reads import read

SUPABASE = "postgresql://postgres.ref:secret@pooler.example.com:5432/db"


def test_postgres_is_used_when_database_url_is_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", SUPABASE)
    db = engine()
    assert db.url.drivername == "postgresql+psycopg"
    assert db.url.query["options"] == "-c search_path=undercover"
    assert isinstance(db.pool, QueuePool)
    assert (db.pool.size(), db.pool._max_overflow, db.pool._pre_ping) == (4, 0, True)
    assert db.pool._timeout == 120
    assert location(db) == "the undercover schema on Postgres"


def test_the_settings_in_database_url_are_kept(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"{SUPABASE}?sslmode=require")
    query = engine().url.query
    assert (query["sslmode"], query["options"]) == (
        "require",
        "-c search_path=undercover",
    )


def test_sqlite_is_used_otherwise(database):
    db = engine()
    assert db.url.drivername == "sqlite"
    assert db.url.database == str(database)
    assert location(db) == "undercover.db"


@pytest.mark.parametrize("empty", [False, True])
def test_startup_seeds_a_missing_or_empty_database(database, empty):
    database.unlink()
    if empty:
        database.touch()
    with TestClient(app) as client:
        assert len(read(client, "/api/claims").json()) == 26


def test_seeding_drops_the_tables_of_earlier_versions():
    old = MetaData()
    for name in RETIRED:
        Table(name, old, Column("run_id", Text))
    old.create_all(engine())
    seed(engine())
    tables = set(inspect(engine()).get_table_names())
    assert not tables & set(RETIRED)
    assert {"runs", "run_claims", "model_calls", "work_times"} <= tables
