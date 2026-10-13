"""MCP tools for the synchronous agent: one server's tools over streamable HTTP,
each call made on an event loop of its own."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StreamableHttpConnection

SERVER = "server"


def run_async[T](work: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to the end on an event loop of its own, closed afterwards,
    which never sets or clears the thread's loop, so the main thread keeps the
    loop Mangum asks for."""
    with asyncio.Runner(loop_factory=asyncio.new_event_loop) as runner:
        return runner.run(work)


class McpTools:
    """The tools of one MCP server, listed once. Each call opens a session of its
    own, since the servers are stateless. A tool the service refuses raises
    LangChain's ToolException with the service's answer, and an MCP error is
    raised as it is."""

    def __init__(self, server: str, url: str, auth: httpx.Auth | None = None) -> None:
        """List the tools of the server named, raising ConnectionError when it
        doesn't answer."""
        connection = StreamableHttpConnection(transport="streamable_http", url=url)
        if auth is not None:
            connection["auth"] = auth
        client = MultiServerMCPClient({SERVER: connection}, handle_tool_errors=False)
        try:
            tools = run_async(client.get_tools())
        except* httpx.TransportError:
            raise ConnectionError(f"{server} isn't answering at {url}") from None
        self.tools = {tool.name: tool for tool in tools}

    def call(self, name: str, inputs: dict[str, Any]) -> str:
        """Call one tool by its name and return the text it answers with."""
        content = run_async(self.tools[name].ainvoke(inputs))
        return "".join(block["text"] for block in content)
