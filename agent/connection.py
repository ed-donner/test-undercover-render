"""The connection to the UnderCover backend: its address, the one HTTP client, the
agent's API key, and how a request is sent and refused. The claim agent's API and the
improver's API send their requests through it with the agent's key, and the
Copilot's with a handler's sign-in."""

import os
from typing import Any

import httpx

from agent.refusals import REFUSED

BACKEND_URL = os.getenv("UNDERCOVER_API", "http://127.0.0.1:8000")
API_KEY_HEADER = "X-API-Key"
MISSING_KEY = "UNDERCOVER_API_KEY is missing. Add it to .env"

# Retries a refused connection for about 7 seconds, while the backend starts.
backend = httpx.Client(
    base_url=f"{BACKEND_URL}/api",
    timeout=30,
    transport=httpx.HTTPTransport(retries=5),
)


class Refused(Exception):
    """The backend refused a request, with its status code and reason."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code, self.detail = status_code, detail

    @property
    def answer(self) -> str:
        """The refusal as a model is answered with it."""
        return REFUSED.format(reason=self.detail)


def api_key() -> str:
    """The agent's API key, read as each request is sent, so it is there for a
    process that loads .env after it imports the agent."""
    key = os.getenv("UNDERCOVER_API_KEY")
    if not key:
        raise RuntimeError(MISSING_KEY)
    return key


def send(method: str, path: str, headers: dict[str, str], **request: Any) -> Any:
    """Send one request to the backend and return its JSON, or raise Refused."""
    response = backend.request(method, path, headers=headers, **request)
    if response.is_error:
        raise Refused(response.status_code, response.json()["detail"])
    return response.json()


def call(method: str, path: str, **request: Any) -> Any:
    """Send one request to the backend with the agent's key."""
    return send(method, path, {API_KEY_HEADER: api_key()}, **request)


def call_as(sign_in: str, method: str, path: str, **request: Any) -> Any:
    """Send one request to the backend as the handler whose sign-in it is, with
    their access token and never the agent's key, as the Copilot does."""
    return send(method, path, {"Authorization": f"Bearer {sign_in}"}, **request)
