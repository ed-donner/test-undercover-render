"""A stand-in for AgentCore Memory in place of AgentCoreMemoryStore. It keeps each
event a put writes, and answers a search in AgentCoreMemoryStore's shape: every
result's namespace is the prefix searched, and a memory's own namespace is only in
its value's namespaces, beside its text in its content. LangGraph's InMemoryStore
would give each result its own namespace, so a filter on the result's namespace
would pass there and drop nothing on AgentCore."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from botocore.exceptions import EndpointConnectionError
from langchain_core.messages import BaseMessage
from langgraph.store.base import BaseStore, Op, PutOp, Result, SearchItem, SearchOp

ENDPOINT = "https://bedrock-agentcore.us-east-1.amazonaws.com"


@dataclass
class Event:
    """An event a put wrote: its actor, its session and its message."""

    actor: str
    session: str
    message: BaseMessage


@dataclass
class MemoryStandIn(BaseStore):
    """The memories AgentCore would have made, each a namespace and a text, the
    events written and the namespaces searched. One that can't be reached raises
    what botocore raises when AgentCore can't be reached."""

    memories: list[tuple[str, str]] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    searched: list[str] = field(default_factory=list)
    reachable: bool = True

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        if not self.reachable:
            raise EndpointConnectionError(endpoint_url=ENDPOINT)
        return [self.handle(op) for op in ops]

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        return self.batch(ops)

    def handle(self, op: Op) -> Result:
        if isinstance(op, PutOp):
            actor, session = op.namespace
            assert op.value is not None
            message = op.value["message"]
            if not isinstance(message, BaseMessage):
                raise ValueError("Value must contain a 'message' key with a message")
            self.events.append(Event(actor, session, message))
            return None
        assert isinstance(op, SearchOp)
        if not op.query:
            return []
        path = "/" + "/".join(op.namespace_prefix)
        self.searched.append(path)
        now = datetime.now(UTC)
        found = [
            SearchItem(
                namespace=op.namespace_prefix,
                key=f"record-{n}",
                value={"content": text, "namespaces": [namespace]},
                created_at=now,
                updated_at=now,
            )
            for n, (namespace, text) in enumerate(self.memories)
            if namespace.startswith(f"{path}/")
        ]
        return found[: op.limit]
