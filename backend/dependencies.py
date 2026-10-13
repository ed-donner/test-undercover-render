"""The FastAPI dependencies the backend's routers share: the database, the gates on
who may call each route (the agent with its key, a signed-in handler, or either),
the handler signed in, and the senior handler an action needs."""

from collections.abc import Callable, Generator
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Connection, select

from backend import api_key, auth
from backend.database import engine, handlers
from backend.lookups import current_settings
from backend.models import Handler
from backend.money import dollars

SIGN_IN_OUT_OF_REACH = "Sign-in can't be checked: Supabase is out of reach"
NOT_SIGNED_IN = "The sign-in isn't valid. Please sign in again."
NEEDS_THE_KEY = "This needs the agent's API key"
NEEDS_A_SIGN_IN_OR_THE_KEY = "Sign in, or send the agent's API key"
API_KEY_HEADER = "X-API-Key"
# The challenges a 401 carries, for a missing or bad sign-in or key.
BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}
API_KEY_CHALLENGE = {"WWW-Authenticate": "APIKey"}


def database() -> Generator[Connection]:
    """Open the database for one request on one connection, and commit at its end.
    A route may commit sooner, as one that asks the agent for something does first,
    so the agent sees it; what it writes afterwards is committed at the end. A
    request that fails is rolled back to its last commit."""
    with engine().connect() as connection:
        yield connection
        connection.commit()


# Committed before the response is sent.
Database = Annotated[Connection, Depends(database, scope="function")]

# Read the agent's key from its header, and a handler's access token from the
# Authorization header; a request without them is left to the gates below.
agent_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)
optional_bearer = HTTPBearer(auto_error=False)
# Reads the access token, and refuses a request without one with a 401.
bearer = HTTPBearer()

AgentKeyHeader = Annotated[str | None, Depends(agent_key_header)]


def handler_with(token: str, db: Connection) -> Handler:
    """Return the handler signed in with a token, or raise a 401 when the token isn't
    valid or a 403 when no handler has its email."""
    try:
        email = auth.email_of(token)
    except auth.NotSignedIn as error:
        raise HTTPException(401, NOT_SIGNED_IN, headers=BEARER_CHALLENGE) from error
    except auth.OutOfReach as error:
        raise HTTPException(503, SIGN_IN_OUT_OF_REACH) from error
    row = db.execute(select(handlers).where(handlers.c.email == email)).mappings()
    handler = row.first()
    if handler is None:
        raise HTTPException(403, f"{email} isn't one of our claims handlers")
    return Handler(**handler)


def signed_in_handler(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    db: Database,
) -> Handler:
    """Return the handler signed in with the request's token."""
    return handler_with(credentials.credentials, db)


def the_agent(key: AgentKeyHeader) -> None:
    """Let through a request with the agent's key, and refuse any other with a 401."""
    if not api_key.is_the_agents(key):
        raise HTTPException(401, NEEDS_THE_KEY, headers=API_KEY_CHALLENGE)


def handler_or_agent(
    key: AgentKeyHeader,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(optional_bearer)
    ],
    db: Database,
) -> None:
    """Let through a request with the agent's key or a signed-in handler's token, and
    refuse one with neither with a 401."""
    if api_key.is_the_agents(key):
        return
    if credentials is None:
        raise HTTPException(401, NEEDS_A_SIGN_IN_OR_THE_KEY, headers=BEARER_CHALLENGE)
    handler_with(credentials.credentials, db)


# The gates of the routes that don't take the handler as a parameter, for a
# route's dependencies: one only the agent's side calls, one both the dashboard
# and the agent call, and one only the dashboard calls. A route that needs the
# handler takes SignedIn, or senior(action), as a parameter instead.
AgentKey = Depends(the_agent)
HandlerOrAgent = Depends(handler_or_agent)
SignedInHandler = Depends(signed_in_handler)
SignedIn = Annotated[Handler, Depends(signed_in_handler)]


def senior(action: str) -> Callable[[Handler, Connection], Handler]:
    """Make the dependency for an action only a handler who can sign off payouts
    over the limit may take: it returns the signed-in handler, or raises a 403 that
    names the action and says why."""

    def senior_handler(handler: SignedIn, db: Database) -> Handler:
        refuse_unless_senior(db, handler, action)
        return handler

    return senior_handler


def refuse_unless_senior(db: Connection, handler: Handler, action: str) -> None:
    """Raise a 403 that names the action and says why, unless the handler can sign
    off payouts over the limit."""
    if not handler.can_approve_over_limit:
        limit = dollars(current_settings(db).approval_limit)
        raise HTTPException(
            403,
            f"Only a handler who can sign off payouts over {limit} can {action}. "
            f"{handler.name} can't.",
        )
