"""What the agent's and the Copilot's AgentCore apps share: getting ready once in
a process, on the first request, behind a lock; reading a payload with a Pydantic
discriminated union, and saying what's wrong with one it can't read without
echoing its values; the health check; registering work as an async task on a
thread of its own, so /ping says HealthyBusy until it ends; and their answers."""

import threading
from collections.abc import Callable
from typing import Any, Literal

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from starlette.exceptions import HTTPException

from agent.console import describe

ACCEPTED = {"accepted": True}
HEALTHY = {"healthy": True}
UNKNOWN_OPERATION = "Unknown operation: it must be one of {expected}"
NO_OPERATION = "The payload names no operation"
NOT_AN_OBJECT = "The payload isn't a JSON object"


class Refusal(Exception):
    """The app won't take the work, and why."""


class Operation(BaseModel):
    """A payload: it names its operation and carries every input, each of the right
    type, and no other."""

    model_config = ConfigDict(extra="forbid", strict=True)


class Health(Operation):
    operation: Literal["health"]


class Ready[T]:
    """What an app needs to work, made once in its process on its first request,
    behind a lock. A failure answers 503, saying what went wrong, and the next
    request tries again."""

    def __init__(self, get_ready: Callable[[], T], not_ready: str) -> None:
        self.get_ready, self.not_ready = get_ready, not_ready
        self.guard = threading.Lock()
        # What getting ready made, once it has, in a box of its own, since it may
        # be anything, even None.
        self.made: tuple[T] | None = None

    def get(self) -> T:
        """Return what the app needs, getting ready first if no request has yet."""
        with self.guard:
            if self.made is None:
                try:
                    self.made = (self.get_ready(),)
                except Exception as error:  # the next request gets ready again
                    message = self.not_ready.format(error=describe(error))
                    raise HTTPException(503, message) from error
            return self.made[0]


def read[P](payloads: TypeAdapter[P], payload: Any) -> P:
    """Read a payload, or refuse it with a 400 that says what's wrong."""
    try:
        return payloads.validate_python(payload)
    except ValidationError as error:
        raise HTTPException(400, what_is_wrong(error)) from error


def what_is_wrong(error: ValidationError) -> str:
    """Say what's wrong with a payload: an operation the app doesn't know, or each
    input that's missing, wrong or extra, without its value."""
    problems = []
    for problem in error.errors():
        if problem["type"] == "union_tag_invalid":
            expected = problem.get("ctx", {}).get("expected_tags")
            problems.append(UNKNOWN_OPERATION.format(expected=expected))
        elif problem["type"] == "union_tag_not_found":
            problems.append(NO_OPERATION)
        elif not problem["loc"]:
            problems.append(NOT_AN_OBJECT)
        else:
            field = ".".join(str(part) for part in problem["loc"][1:])
            problems.append(f"{field}: {problem['msg']}")
    return "; ".join(problems)


def is_the_health_check(payload: Any) -> bool:
    """Say whether a payload is the health check."""
    try:
        Health.model_validate(payload)
    except ValidationError:
        return False
    return True


def in_background(
    app: BedrockAgentCoreApp, name: str, work: Callable[[], object]
) -> None:
    """Register the work with the AgentCore app, so its /ping says HealthyBusy
    until the work ends, however it ends, and run it on a thread of its own."""
    task_id = app.add_async_task(name)

    def run() -> None:
        try:
            work()
        finally:
            app.complete_async_task(task_id)

    threading.Thread(target=run, name=name, daemon=True).start()
