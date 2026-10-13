"""A stand-in for boto3's client for AgentCore Runtime, which the agent's and the
Copilot's runtimes share in the tests."""

import io

import pytest
from botocore.exceptions import ClientError

from backend import runtime_calls

ENDPOINT = "https://bedrock-agentcore.us-east-1.amazonaws.com"


def conflict() -> ClientError:
    """What Runtime answers while it starts or stops the session a call names."""
    return ClientError(
        {
            "Error": {
                "Code": runtime_calls.CONFLICT,
                "Message": "The session is starting",
            }
        },
        "InvokeAgentRuntime",
    )


class Clock:
    """Stands in for the clock the calls to Runtime keep: a wait moves it on at
    once, and it keeps each wait."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


class RuntimeStandIn:
    """Stands in for boto3's client for AgentCore Runtime: it keeps each call and
    when it came by the clock, and answers with the status and body given, or
    raises the error given, while the request is sent or as its answer is read.
    It can answer the first calls with a conflict, each taking a while by the
    clock."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.calls: list[dict] = []
        self.called_at: list[float] = []
        self.answer: tuple[int, bytes] = (200, b'{"accepted": true}')
        self.raises: Exception | None = None
        self.cut_off: Exception | None = None
        self.conflicts = 0
        self.conflict_delay = 0.0

    def invoke_agent_runtime(self, **call):
        self.calls.append(call)
        self.called_at.append(self.clock.now)
        if self.conflicts:
            self.conflicts -= 1
            self.clock.now += self.conflict_delay
            raise conflict()
        if self.raises:
            raise self.raises
        status, body = self.answer
        stream = io.BytesIO(body)
        if self.cut_off:
            cut_off = self.cut_off

            def read():
                raise cut_off

            stream.read = read  # type: ignore[method-assign]
        return {"statusCode": status, "response": stream}


def runtime_at(
    monkeypatch: pytest.MonkeyPatch, setting: str, arn: str
) -> RuntimeStandIn:
    """Send a service's work to a stand-in for its runtime, named by its setting,
    on a clock of the test's own."""
    monkeypatch.setenv(setting, arn)
    clock = Clock()
    stand_in = RuntimeStandIn(clock)
    monkeypatch.setattr(runtime_calls, "runtime_client", lambda: stand_in)
    monkeypatch.setattr(runtime_calls, "time", clock)
    return stand_in
