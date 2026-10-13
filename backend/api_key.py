"""The agent's API key, which the agent's side sends with every request, the app
sends the agent's AgentCore app on the laptop, and the backend reads from
UNDERCOVER_API_KEY."""

import os
import secrets


def the_agents_key() -> str:
    """The agent's key, or nothing when none is set."""
    return os.getenv("UNDERCOVER_API_KEY", "")


def is_the_agents(key: str | None) -> bool:
    """Say whether a request's key is the agent's, compared in constant time. With no
    key set, no key is."""
    expected = the_agents_key()
    if not expected or key is None:
        return False
    return secrets.compare_digest(key.encode(), expected.encode())
