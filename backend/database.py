"""The UnderCover database, seeded from the business data in data/, and the plans
and the documents from the context layer's files in context/.

The same tables and queries serve Postgres on Supabase, when DATABASE_URL is set, and
SQLite otherwise, as in the tests.
"""

import json
import os
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Connection,
    Engine,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
    insert,
    inspect,
    select,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema

from backend import context_files
from backend.free_models import model_or_free, models_or_free
from backend.models import (
    EvaluationSet,
    ModelAllowed,
    SettingsValues,
    Status,
    Verdict,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CLAIMS_MANUAL = "claims_manual"
DOCUMENTS = {"policy_wording": "Policy wording", CLAIMS_MANUAL: "Claims manual"}
INSTRUCTIONS = Path(__file__).resolve().parent / "instructions"
# Version 1 is kept from the start, so the current version is the newest kept.
FIRST_VERSION = {
    "number": 1,
    "reason": "The claim agent as the claims team built it",
    "proposed_by": "The claims team",
    "verdict": Verdict.KEPT,
    "verdict_reason": "the first version",
}
# The model version 1 of the claim agent is on, with no reasoning, so a higher
# reasoning effort is an improvement to find, unless a student is on a free model.
FIRST_MODEL = ("openai/gpt-6-luna", "none")
FIRST_RECIPE = {
    "number": 1,
    "recipe": (INSTRUCTIONS / "recipe.md").read_text(encoding="utf-8"),
    "reason": "The lab's first recipe, which tries the models and reasoning efforts "
    "not yet tried, then adds a rule for each mistake",
    "proposed_by": "The claims team",
}
HELD_OUT_CLAIMS = "evals/held_out_claims.json"
SCHEMA = "undercover"
CONNECTIONS = 4
CONNECTION_WAIT = 120
# Tables of earlier versions, dropped before the others, since on Postgres a foreign
# key of theirs would stop the tables they refer to being dropped.
RETIRED = ["todos"]

metadata = MetaData()

# The platform's settings, one row for each change; the newest row is in force.
settings = Table(
    "settings",
    metadata,
    Column("number", Integer, primary_key=True, autoincrement=False),
    Column("approval_limit", Float, nullable=False),
    Column("objectives", JSON, nullable=False),
    Column("noise", JSON, nullable=False),
    Column("tolerance", JSON, nullable=False),
    Column("spending_limit", Float, nullable=False),
    Column("agents", Integer, nullable=False),
    Column("changed_by", Text),
    Column("changed_at", Text, nullable=False),
)
payout_rules = Table(
    "payout_rules",
    metadata,
    Column("plans", JSON, nullable=False),
)
models_allowed = Table(
    "models_allowed",
    metadata,
    Column("model", Text, primary_key=True),
    Column("position", Integer, nullable=False),
    Column("reasoning_efforts", JSON, nullable=False),
    Column("input_price", Float, nullable=False),
    Column("output_price", Float, nullable=False),
)
documents = Table(
    "documents",
    metadata,
    Column("name", Text, primary_key=True),
    Column("position", Integer, nullable=False),
    Column("title", Text, nullable=False),
    Column("text", Text, nullable=False),
    # The version in the document's front matter, such as the manual's 2026.2.
    Column("version", Text, nullable=False),
)
handlers = Table(
    "handlers",
    metadata,
    Column("handler_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("email", Text, nullable=False, unique=True),
    Column("can_approve_over_limit", Boolean, nullable=False),
)
customers = Table(
    "customers",
    metadata,
    Column("customer_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("record", JSON, nullable=False),
)
policies = Table(
    "policies",
    metadata,
    Column("policy_id", Text, primary_key=True),
    Column("record", JSON, nullable=False),
)
claims = Table(
    "claims",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("customer_id", Text, ForeignKey("customers.customer_id"), nullable=False),
    Column("record", JSON, nullable=False),
    Column("status", Text, nullable=False),
    Column("thread_id", Text),
    Column("attempts", Integer, nullable=False),
    Column("evaluation_id", Text, ForeignKey("runs.run_id")),
    Column("copy_of", Text),
    # When the agent last said a resume was working on the claim.
    Column("resume_heard_at", Text),
)
held_out_claims = Table(
    "held_out_claims",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("record", JSON, nullable=False),
)
handler_decisions = Table(
    "handler_decisions",
    metadata,
    Column("evaluation_set", Text, primary_key=True),
    Column("claim_id", Text, primary_key=True),
    Column("decision", Text, nullable=False),
    Column("payout", Float, nullable=False),
    Column("tiny", Boolean, nullable=False),
    Column("reason", Text, nullable=False),
    Column("reference", Text, nullable=False),
)
decisions = Table(
    "decisions",
    metadata,
    Column("claim_id", Text, ForeignKey("claims.claim_id"), primary_key=True),
    Column("decision", Text, nullable=False),
    Column("payout", Float, nullable=False),
    Column("section", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
    # Who or what made the decision, and the claims manual's version in force.
    Column("decided_by", Text, nullable=False),
    Column("manual_version", Text, nullable=False),
    # An approval's calculation, its lines and its payout, and none otherwise.
    Column("calculation", JSON),
    # The approval limit in force when the decision was recorded.
    Column("approval_limit", Float, nullable=False),
    Column("signed_off_by", Text),
    Column("signed_off_at", Text),
    # Why the Gateway refused to pay an approval, which then waits for sign-off.
    Column("gateway_refusal", Text),
)
# The decisions handlers sent back to the agent, each with its note, who sent it
# back and when.
sent_back_decisions = Table(
    "sent_back_decisions",
    metadata,
    Column("sent_back_id", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
    Column("decision", Text, nullable=False),
    Column("payout", Float, nullable=False),
    Column("calculation", JSON),
    Column("section", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("decided_by", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
    Column("manual_version", Text, nullable=False),
    Column("gateway_refusal", Text),
    Column("note", Text, nullable=False),
    Column("sent_back_by", Text, nullable=False),
    Column("sent_back_at", Text, nullable=False),
)
# Each claim's latest calculation of its payout, on the thread of the attempt it was
# made in, which an approval in that attempt must match.
calculations = Table(
    "calculations",
    metadata,
    Column("claim_id", Text, ForeignKey("claims.claim_id"), primary_key=True),
    Column("thread_id", Text, nullable=False),
    Column("lines", JSON, nullable=False),
    Column("payout", Float, nullable=False),
    Column("calculated_at", Text, nullable=False),
)
payments = Table(
    "payments",
    metadata,
    Column("claim_id", Text, ForeignKey("claims.claim_id"), primary_key=True),
    Column("amount", Float, nullable=False),
    Column("paid_at", Text, nullable=False),
)
steps = Table(
    "steps",
    metadata,
    Column("step_id", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
    Column("thread_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("content", Text, nullable=False),
    # The context files a lookup came from, each with its source.
    Column("sources", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
)
# The improver's rounds, each to the settings, the recipe and the version of the
# claim agent in force when it started.
rounds = Table(
    "rounds",
    metadata,
    Column("number", Integer, primary_key=True),
    Column("round_id", Text, nullable=False, unique=True),
    Column("thread_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("settings", Integer, ForeignKey("settings.number"), nullable=False),
    Column("recipe", Integer, nullable=False),
    Column("starting_version", Integer, nullable=False),
    # The sets of the first evaluations the starting version still needed.
    Column("first_evaluations", JSON, nullable=False),
    Column("improver_model", Text, nullable=False),
    Column("improver_reasoning_effort", Text, nullable=False),
    Column("started_by", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("finished_at", Text),
    Column("stopped_by", Text),
    Column("stopped_because", Text),
    Column("held_out_before", JSON),
    Column("held_out_after", JSON),
    # When the app last heard of the round's work: as it started the round or
    # recorded a review, or from the agent's heartbeat.
    Column("heard_at", Text),
)
recipes = Table(
    "recipes",
    metadata,
    Column("number", Integer, primary_key=True, autoincrement=False),
    Column("recipe", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("proposed_by", Text, nullable=False),
    Column("round_id", Text, ForeignKey("rounds.round_id")),
    Column("approved_by", Text),
    Column("approved_at", Text),
    Column("created_at", Text, nullable=False),
)
# The improver's proposals, each waiting for a handler until it is reviewed.
proposals = Table(
    "proposals",
    metadata,
    Column("proposal_id", Text, primary_key=True),
    Column("round_id", Text, ForeignKey("rounds.round_id"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("proposal", JSON, nullable=False),
    Column("proposed_at", Text, nullable=False),
    Column("review", Text),
    Column("reviewed_by", Text),
    Column("reviewed_at", Text),
    Column("rejection_reason", Text),
)
improver_calls = Table(
    "improver_calls",
    metadata,
    Column("improver_call_id", Integer, primary_key=True),
    Column("round_id", Text, ForeignKey("rounds.round_id"), nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost", Float, nullable=False),
    Column("created_at", Text, nullable=False),
)
versions = Table(
    "versions",
    metadata,
    Column("number", Integer, primary_key=True, autoincrement=False),
    Column("instructions", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("reasoning_effort", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("proposed_by", Text, nullable=False),
    # The version this one changes, which was current when it was proposed.
    Column("based_on", Integer, ForeignKey("versions.number")),
    Column("round_id", Text, ForeignKey("rounds.round_id")),
    Column("approved_by", Text),
    Column("approved_at", Text),
    Column("created_at", Text, nullable=False),
    Column("verdict", Text),
    Column("verdict_reason", Text),
)
runs = Table(
    "runs",
    metadata,
    Column("number", Integer, primary_key=True),
    Column("run_id", Text, nullable=False, unique=True),
    Column("kind", Text, nullable=False),
    Column("agents", Integer, nullable=False),
    Column("version", Integer, ForeignKey("versions.number"), nullable=False),
    Column("round_id", Text, ForeignKey("rounds.round_id")),
    Column("model", Text, nullable=False),
    Column("reasoning_effort", Text, nullable=False),
    Column("evaluation_set", Text),
    Column("tiny", Boolean),
    Column("status", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("finished_at", Text),
    Column("summary", JSON),
    Column("stopped_because", Text),
    # When the app last heard of the run's work: as it created the run, or from
    # the agent's heartbeat.
    Column("heard_at", Text),
)
# One row, which a start of the agent's work updates first in its transaction, so
# two starts at the same moment take turns.
locks = Table(
    "locks",
    metadata,
    Column("name", Text, primary_key=True),
    Column("taken_at", Text),
)
AGENTS_WORK = "the agent's work"
# The judge's grade of each copy in an evaluation, empty when it couldn't grade it.
grades = Table(
    "grades",
    metadata,
    Column("claim_id", Text, ForeignKey("claims.claim_id"), primary_key=True),
    Column("run_id", Text, ForeignKey("runs.run_id"), nullable=False),
    Column("score", Float),
    Column("letter", Text),
    Column("same_grounds", Float),
    Column("same_section", Float),
    Column("cost", Float, nullable=False),
    Column("graded_at", Text, nullable=False),
)
run_claims = Table(
    "run_claims",
    metadata,
    Column("run_id", Text, ForeignKey("runs.run_id"), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
)
model_calls = Table(
    "model_calls",
    metadata,
    Column("model_call_id", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
    Column("thread_id", Text, nullable=False),
    Column("run_id", Text, ForeignKey("runs.run_id")),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost", Float, nullable=False),
    Column("created_at", Text, nullable=False),
)
work_times = Table(
    "work_times",
    metadata,
    Column("work_time_id", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
    Column("thread_id", Text, nullable=False),
    Column("run_id", Text, ForeignKey("runs.run_id")),
    Column("started_at", Text, nullable=False),
    Column("seconds", Float, nullable=False),
)


class LabeledSet(NamedTuple):
    """A set of claims our handlers have decided: the table its claims are kept in,
    and the file in data/evals/ with the handlers' decisions, which only seeding
    reads."""

    claims: Table
    decisions: str


LABELED_SETS = {
    EvaluationSet.EVALUATION: LabeledSet(claims, "evals/decisions.json"),
    EvaluationSet.HELD_OUT: LabeledSet(
        held_out_claims, "evals/held_out_decisions.json"
    ),
}

claim_view = (
    select(
        claims.c.claim_id,
        claims.c.record,
        claims.c.status,
        claims.c.thread_id,
        claims.c.attempts,
        claims.c.evaluation_id,
        claims.c.copy_of,
        claims.c.resume_heard_at,
        customers.c.name.label("customer_name"),
        decisions.c.decision,
        decisions.c.payout,
        decisions.c.section,
        decisions.c.reason,
        decisions.c.decided_at,
        decisions.c.decided_by,
        decisions.c.manual_version,
        decisions.c.calculation,
        decisions.c.approval_limit,
        decisions.c.signed_off_by,
        decisions.c.signed_off_at,
        decisions.c.gateway_refusal,
        payments.c.amount,
        payments.c.paid_at,
    )
    .join(customers, customers.c.customer_id == claims.c.customer_id)
    .outerjoin(decisions, decisions.c.claim_id == claims.c.claim_id)
    .outerjoin(payments, payments.c.claim_id == claims.c.claim_id)
)


def stamp(moment: datetime) -> str:
    """Write a moment in UTC to the second, as every record has it."""
    return moment.isoformat(timespec="seconds")


def now() -> str:
    """Return the current time in UTC, to the second."""
    return stamp(datetime.now(UTC))


def database_url() -> URL:
    """Return Postgres at DATABASE_URL, through psycopg and in our own schema, or
    SQLite at UNDERCOVER_DB or undercover.db."""
    if url := os.getenv("DATABASE_URL"):
        postgres = make_url(url).set(drivername="postgresql+psycopg")
        return postgres.update_query_dict({"options": f"-c search_path={SCHEMA}"})
    path = os.getenv("UNDERCOVER_DB", str(ROOT / "undercover.db"))
    return URL.create("sqlite", database=path)


def on_postgres(url: URL) -> bool:
    """Say whether a database is Postgres rather than SQLite."""
    return url.get_backend_name() == "postgresql"


def on_lambda() -> bool:
    """Say whether the backend runs on AWS Lambda, which sets this for every
    function."""
    return "AWS_LAMBDA_FUNCTION_NAME" in os.environ


@cache
def engine_for(url: URL, for_lambda: bool) -> Engine:
    """Open a database: on Lambda, Postgres with a connection for each request and
    no prepared statements, for Supabase's transaction pooler, since each copy of
    the function would keep its own pool; elsewhere Postgres with at most
    CONNECTIONS connections, waiting up to CONNECTION_WAIT seconds for one, or
    SQLite with a connection for each request."""
    if on_postgres(url) and for_lambda:
        return create_engine(
            url, poolclass=NullPool, connect_args={"prepare_threshold": None}
        )
    if on_postgres(url):
        return create_engine(
            url,
            pool_size=CONNECTIONS,
            max_overflow=0,
            pool_timeout=CONNECTION_WAIT,
            pool_pre_ping=True,
        )
    return create_engine(url, poolclass=NullPool)


def engine() -> Engine:
    """Return the backend's database."""
    return engine_for(database_url(), on_lambda())


def location(db: Engine) -> str:
    """Say where a database is, for a person to read."""
    if on_postgres(db.url):
        return f"the {SCHEMA} schema on Postgres"
    return Path(str(db.url.database)).name


def is_seeded(db: Engine) -> bool:
    """Say whether the database has its tables."""
    return inspect(db).has_table("claims")


def load(name: str) -> Any:
    """Read one of the JSON files in data/."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def queue_records(name: str) -> list[dict[str, Any]]:
    """Read the queue's records of one kind: those in data/ and the security team's
    in data/security/, whose handler's decision is never seeded."""
    return load(name) + load(f"security/{name}")


def waiting_claim(record: dict[str, Any], **columns: Any) -> dict[str, Any]:
    """Return the row of a claim waiting in the queue, never started, with any other
    columns given."""
    return {
        "claim_id": record["claim_id"],
        "customer_id": record["customer_id"],
        "record": record,
        "status": Status.WAITING,
        "thread_id": None,
        "attempts": 0,
    } | columns


def seed(db: Engine) -> dict[str, int]:
    """Build the tables afresh from data/ and count what they hold."""
    company = load("company.json")
    handler_rows = load("handlers.json")
    customer_rows = queue_records("customers.json")
    policy_rows = queue_records("policies.json")
    claim_rows = queue_records("claims.json")
    with db.begin() as connection:
        if on_postgres(db.url):
            connection.execute(CreateSchema(SCHEMA, if_not_exists=True))
        for name in RETIRED:
            Table(name, MetaData()).drop(connection, checkfirst=True)
        metadata.drop_all(connection)
        metadata.create_all(connection)
        seed_settings(connection, company["payout_approval_limit"])
        connection.execute(insert(payout_rules).values(plans=context_files.plans()))
        seed_models_allowed(connection)
        seed_documents(connection)
        connection.execute(
            insert(handlers),
            [
                {
                    "handler_id": h["handler_id"],
                    "name": h["name"],
                    "role": h["role"],
                    "email": h["email"],
                    "can_approve_over_limit": h["can_approve_over_limit"],
                }
                for h in handler_rows
            ],
        )
        connection.execute(
            insert(customers),
            [
                {"customer_id": c["customer_id"], "name": c["name"], "record": c}
                for c in customer_rows
            ],
        )
        connection.execute(
            insert(policies),
            [{"policy_id": p["policy_id"], "record": p} for p in policy_rows],
        )
        connection.execute(insert(claims), [waiting_claim(c) for c in claim_rows])
        seed_first_version(connection)
        connection.execute(insert(recipes).values(**FIRST_RECIPE, created_at=now()))
        connection.execute(insert(locks).values(name=AGENTS_WORK))
        labeled = seed_evaluations(connection)
    return {
        "claims": len(claim_rows),
        "policies": len(policy_rows),
        "customers": len(customer_rows),
        "handlers": len(handler_rows),
    } | labeled


def seed_documents(connection: Connection) -> None:
    """Store the policy wording and the claims manual from the context layer's
    files, each with its version."""
    rows = []
    for position, (name, title) in enumerate(DOCUMENTS.items()):
        text, version = context_files.document(name)
        rows.append(
            {
                "name": name,
                "position": position,
                "title": title,
                "text": text,
                "version": version,
            }
        )
    connection.execute(insert(documents), rows)


def seed_settings(connection: Connection, approval_limit: float) -> None:
    """Store the first settings: the approval limit, and the rest from
    data/improvement.json, checked as the settings page checks a change."""
    values = SettingsValues(approval_limit=approval_limit, **load("improvement.json"))
    connection.execute(
        insert(settings).values(number=1, **values.model_dump(), changed_at=now())
    )


def seed_models_allowed(connection: Connection) -> None:
    """Store the models the claim agent may use, from data/models.json, or the free
    model alone for students on free models."""
    listed = [ModelAllowed(**model) for model in load("models.json")]
    connection.execute(
        insert(models_allowed),
        [
            model.model_dump() | {"position": position}
            for position, model in enumerate(models_or_free(listed))
        ],
    )


def seed_first_version(connection: Connection) -> None:
    """Make version 1 of the claim agent's configuration, from its instructions file,
    on GPT-6 Luna with no reasoning, or the free model for students on free
    models."""
    model, reasoning_effort = model_or_free(*FIRST_MODEL)
    connection.execute(
        insert(versions).values(
            **FIRST_VERSION,
            instructions=(INSTRUCTIONS / "claim.md").read_text(encoding="utf-8"),
            model=model,
            reasoning_effort=reasoning_effort,
            created_at=now(),
        )
    )


def seed_evaluations(connection: Connection) -> dict[str, int]:
    """Store the held-out claims, out of the queue, and the handlers' decisions on
    both labeled sets, and count them."""
    held_out = load(HELD_OUT_CLAIMS)
    connection.execute(
        insert(held_out_claims),
        [{"claim_id": c["claim_id"], "record": c} for c in held_out],
    )
    rows = [
        {
            "evaluation_set": evaluation_set,
            "claim_id": d["claim_id"],
            "decision": d["decision"],
            "payout": d["payout"],
            "tiny": d["tiny"],
            "reason": d["reason"],
            "reference": d["reference"],
        }
        for evaluation_set, labeled in LABELED_SETS.items()
        for d in load(labeled.decisions)
    ]
    connection.execute(insert(handler_decisions), rows)
    return {"held_out_claims": len(held_out), "handler_decisions": len(rows)}
