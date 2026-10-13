"""Checking the agent's API key, which the agent's side sends with every request and
the backend reads from UNDERCOVER_API_KEY."""

import os
import secrets


def is_the_agents(key: str | None) -> bool:
    """Say whether a request's key is the agent's, compared in constant time. With no
    key set, no key is."""
    expected = os.getenv("UNDERCOVER_API_KEY", "")
    if not expected or key is None:
        return False
    return secrets.compare_digest(key.encode(), expected.encode())
