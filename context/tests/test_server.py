"""The context layer's server: its tools follow the API rules, and its Lambda
handler answers a Function URL's requests, one after another in one process."""

import json
from typing import Any

import pytest

from api_rules import rule_breaks
from context.server import handler
from context.tests.function_url import Context, mcp_request

TOOLS = {
    "lookup_term",
    "describe_fields",
    "get_plan",
    "get_claim_rules",
    "search_reference_data",
    "search_documents",
    "read_section",
}


def through_the_handler(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Send one MCP request through the Lambda handler, and return its result."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    answer = handler(mcp_request(json.dumps(body)), Context())
    assert answer["statusCode"] == 200
    return json.loads(answer["body"])["result"]


def as_operations(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """The tools as API operations, each taking its inputs as its body, so the API
    rules can check them as they check the app's."""
    body = {"required": True, "content": {"application/json": {"schema": {}}}}
    paths, models = {}, {}
    for tool in tools:
        name = tool["name"]
        schema = {"$ref": f"#/components/schemas/{name}"}
        content = {"application/json": {"schema": schema}}
        operation = {"operationId": name, "description": tool["description"]}
        paths[f"/{name}"] = {
            "post": operation | {"requestBody": body | {"content": content}}
        }
        models[name] = tool["inputSchema"]
    return {"paths": paths, "components": {"schemas": models}}


def test_the_handler_lists_the_tools_then_calls_one():
    tools = through_the_handler("tools/list", {})["tools"]
    assert {tool["name"] for tool in tools} == TOOLS
    found = through_the_handler(
        "tools/call", {"name": "lookup_term", "arguments": {"term": "unattended"}}
    )
    assert not found["isError"]
    assert json.loads(found["content"][0]["text"])["sections"] == [5]


def test_every_tool_is_read_only_and_follows_the_api_rules():
    tools = through_the_handler("tools/list", {})["tools"]
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    assert rule_breaks(as_operations(tools)) == []


def test_a_section_that_doesnt_exist_is_refused_with_its_reason():
    arguments = {"document": "claims_manual", "number": 99}
    refused = through_the_handler(
        "tools/call", {"name": "read_section", "arguments": arguments}
    )
    assert refused["isError"]
    assert refused["content"][0]["text"].endswith(
        "Section 99 of the claims manual not found"
    )
    outside = through_the_handler(
        "tools/call", {"name": "get_plan", "arguments": {"plan": "platinum"}}
    )
    assert outside["isError"]


@pytest.mark.parametrize("tool", ["search_documents", "search_reference_data"])
@pytest.mark.parametrize("query", ["", "   "])
def test_a_search_with_nothing_to_look_for_is_refused(tool, query):
    refused = through_the_handler(
        "tools/call", {"name": tool, "arguments": {"query": query}}
    )
    assert refused["isError"]
    assert "at least 1 character" in refused["content"][0]["text"]
