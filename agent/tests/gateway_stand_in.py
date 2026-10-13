"""A stand-in for the AgentCore Gateway: an MCP server whose tools are named as the
Gateway names them. undercover-app___<operation> is each operation in the agent's
API document, sent to the test backend with the agent's key, which the Gateway's
credential provider holds, and the app's refusals come back as tool errors with the
app's answer. undercover-context___<tool> is each of the context layer's tools,
answered by the context layer's own server, its refusals as tool errors. Its
Policy refuses a payment over $1,000, and any tool a test names, with an MCP
error, as the Gateway's Policy does. It keeps each call's name, its inputs and
whether it was signed with SigV4 for bedrock-agentcore."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import anyio
from fastapi.testclient import TestClient
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from starlette.applications import Starlette
from starlette.routing import Route

from agent.gateway import SEPARATOR, SERVICE
from agent.routes import Target
from backend import agent_api
from backend.dependencies import API_KEY_HEADER
from backend.main import app
from context.server import build_server

PAY_CLAIM = f"{Target.APP}{SEPARATOR}pay_claim"
CONTEXT = f"{Target.CONTEXT}{SEPARATOR}"
LIMIT = 1000.0
DENIED = "Tool Execution Denied: Tool call not allowed due to policy enforcement"
SIGNED_FOR = f"/{SERVICE}/aws4_request"


@dataclass
class Operation:
    """One of the app's operations, as the Gateway's tool for it calls it."""

    method: str
    path: str
    in_path: list[str]
    in_query: list[str]
    tool: types.Tool


@dataclass
class Call:
    """A call to one of the stand-in's tools."""

    name: str
    inputs: dict[str, Any]
    signed: bool


def inline(schema: Any, schemas: dict[str, Any]) -> Any:
    """A schema with the schemas it refers to written in, as a tool's inputs are."""
    if isinstance(schema, dict):
        if "$ref" in schema:
            return inline(schemas[schema["$ref"].split("/")[-1]], schemas)
        return {key: inline(value, schemas) for key, value in schema.items()}
    if isinstance(schema, list):
        return [inline(value, schemas) for value in schema]
    return schema


def app_operations(document: dict[str, Any]) -> dict[str, Operation]:
    """The Gateway's tool for each operation in the agent's API document, whose
    inputs are the operation's path and query parameters and its body's fields."""
    schemas = document["components"]["schemas"]
    operations = {}
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            parameters = operation.get("parameters", [])
            properties = {p["name"]: p["schema"] for p in parameters}
            required = [p["name"] for p in parameters if p["required"]]
            if body := operation.get("requestBody"):
                model = inline(body["content"]["application/json"]["schema"], schemas)
                properties |= model["properties"]
                required += model["required"]
            name = f"{Target.APP}{SEPARATOR}{operation['operationId']}"
            inputs = {"type": "object", "properties": properties, "required": required}
            operations[name] = Operation(
                method.upper(),
                path,
                [p["name"] for p in parameters if p["in"] == "path"],
                [p["name"] for p in parameters if p["in"] == "query"],
                types.Tool(
                    name=name,
                    description=operation["description"],
                    inputSchema=inline(inputs, schemas),
                ),
            )
    return operations


@dataclass
class GatewayStandIn:
    """The stand-in Gateway, the calls made to it and the tools a test has its
    Policy refuse."""

    url: str = ""
    calls: list[Call] = field(default_factory=list)
    refused: set[str] = field(default_factory=set)
    operations: dict[str, Operation] = field(
        default_factory=lambda: app_operations(agent_api.document(app))
    )
    backend: TestClient = field(default_factory=lambda: TestClient(app))
    server: Server = field(default_factory=lambda: Server("undercover-gateway"))
    context: FastMCP = field(default_factory=build_server)

    def __post_init__(self) -> None:
        self.server.request_handlers[types.ListToolsRequest] = self.list_tools
        self.server.request_handlers[types.CallToolRequest] = self.call_tool

    def reset(self) -> None:
        """Forget the calls made, and refuse only what the Policy always refuses."""
        self.calls.clear()
        self.refused.clear()

    @property
    def names(self) -> list[str]:
        """The names of the tools called, in order."""
        return [call.name for call in self.calls]

    async def list_tools(self, _: types.ListToolsRequest) -> types.ServerResult:
        context_tools = [
            tool.model_copy(update={"name": f"{CONTEXT}{tool.name}"})
            for tool in await self.context.list_tools()
        ]
        tools = [operation.tool for operation in self.operations.values()]
        return types.ServerResult(types.ListToolsResult(tools=tools + context_tools))

    async def call_tool(self, request: types.CallToolRequest) -> types.ServerResult:
        """Keep the call, then refuse it as the Policy does or answer it, an
        error's answer as a tool error."""
        name, inputs = request.params.name, request.params.arguments or {}
        http = self.server.request_context.request
        signed = http is not None and SIGNED_FOR in http.headers.get(
            "authorization", ""
        )
        self.calls.append(Call(name, inputs, signed))
        if self.policy_refuses(name, inputs):
            raise McpError(types.ErrorData(code=types.INVALID_REQUEST, message=DENIED))
        if name.startswith(CONTEXT):
            answer = await self.look_up(name.removeprefix(CONTEXT), inputs)
            return types.ServerResult(answer)
        answer, refused = await anyio.to_thread.run_sync(self.send, name, inputs)
        text = types.TextContent(type="text", text=answer)
        return types.ServerResult(types.CallToolResult(content=[text], isError=refused))

    def policy_refuses(self, name: str, inputs: dict[str, Any]) -> bool:
        over_the_limit = name == PAY_CLAIM and inputs["amount"] > LIMIT
        return over_the_limit or name in self.refused

    async def look_up(self, tool: str, inputs: dict[str, Any]) -> types.CallToolResult:
        """Answer one of the context layer's tools with the context layer's own
        server, its answer as structured content too, as its output schema asks,
        or its refusal as a tool error."""
        try:
            called = await self.context.call_tool(tool, inputs)
        except ToolError as refusal:
            text = types.TextContent(type="text", text=str(refusal))
            return types.CallToolResult(content=[text], isError=True)
        # A tool with an output schema answers with its content and its structure.
        content, answer = cast(tuple[list[types.ContentBlock], dict[str, Any]], called)
        return types.CallToolResult(content=content, structuredContent=answer)

    def send(self, name: str, inputs: dict[str, Any]) -> tuple[str, bool]:
        """Send a call to the app's operation, with the agent's key, and return its
        answer and whether the app refused it."""
        operation = self.operations[name]
        path = operation.path.format(**{key: inputs[key] for key in operation.in_path})
        params = {key: inputs[key] for key in operation.in_query}
        named = {*operation.in_path, *operation.in_query}
        body = {key: value for key, value in inputs.items() if key not in named}
        response = self.backend.request(
            operation.method,
            path,
            params=params,
            json=body or None,
            headers={API_KEY_HEADER: os.environ["UNDERCOVER_API_KEY"]},
        )
        return response.text, response.is_error

    def asgi(self) -> Starlette:
        """The stand-in as an app, serving MCP at /mcp, stateless, in JSON."""
        manager = StreamableHTTPSessionManager(
            self.server, stateless=True, json_response=True
        )

        @asynccontextmanager
        async def lifespan(_: Starlette) -> AsyncIterator[None]:
            async with manager.run():
                yield

        mcp = Route("/mcp", endpoint=StreamableHTTPASGIApp(manager))
        return Starlette(routes=[mcp], lifespan=lifespan)
