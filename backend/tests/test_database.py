import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, Text, inspect, select, update
from sqlalchemy.pool import QueuePool

from backend import dependencies
from backend.database import RETIRED, claims, engine, location, seed
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


def status_of(claim_id):
    with engine().connect() as db:
        query = select(claims.c.status).where(claims.c.claim_id == claim_id)
        return db.execute(query).scalar_one()


def decide_in(db, claim_id):
    db.execute(
        update(claims).where(claims.c.claim_id == claim_id).values(status="decided")
    )


def test_a_request_commits_at_its_end(database):
    request = dependencies.database()
    decide_in(next(request), "CLM-1001")
    assert status_of("CLM-1001") == "waiting"
    with pytest.raises(StopIteration):
        next(request)
    assert status_of("CLM-1001") == "decided"


def test_a_route_can_commit_sooner_and_a_failure_keeps_only_that(database):
    request = dependencies.database()
    db = next(request)
    decide_in(db, "CLM-1001")
    db.commit()
    assert status_of("CLM-1001") == "decided"
    decide_in(db, "CLM-1003")
    with pytest.raises(HTTPException):
        request.throw(HTTPException(409, "Refused"))
    assert (status_of("CLM-1001"), status_of("CLM-1003")) == ("decided", "waiting")
