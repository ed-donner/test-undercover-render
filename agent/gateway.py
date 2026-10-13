"""The Gateway route: the claim agent's tools and its payment as the AgentCore
Gateway's MCP tools, each request signed for bedrock-agentcore with the AWS CLI's
credentials and region, so the Gateway's Policy sees every call."""

import json
import os
from collections.abc import Generator
from typing import Any

import boto3
import httpx
from botocore.auth import SigV4Auth as BotocoreSigV4Auth
from botocore.awsrequest import AWSRequest
from mcp.shared.exceptions import McpError

from agent.mcp_tools import McpTools
from agent.routes import GatewayRefused, Target

GATEWAY_URL = "UNDERCOVER_GATEWAY_URL"
GATEWAY = "The Gateway"
SERVICE = "bedrock-agentcore"
# The Gateway names each tool <target>___<operation>.
SEPARATOR = "___"
SIGNATURE_HEADERS = ("Authorization", "X-Amz-Date", "X-Amz-Security-Token")


class SigV4Auth(httpx.Auth):
    """Sign each request with AWS Signature Version 4 for the Gateway, as boto3
    signs its own calls, with the credentials and region of a boto3 session."""

    requires_request_body = True

    def __init__(self, session: boto3.Session) -> None:
        self.credentials = session.get_credentials()
        self.region = session.region_name

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        headers = {
            "Host": request.url.netloc.decode(),
            "Content-Type": request.headers.get("content-type", ""),
        }
        signed = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers=headers,
        )
        credentials = self.credentials.get_frozen_credentials()
        BotocoreSigV4Auth(credentials, SERVICE, self.region).add_auth(signed)
        for name in SIGNATURE_HEADERS:
            if name in signed.headers:
                request.headers[name] = signed.headers[name]
        yield request


class Gateway:
    """The Gateway's tools, listed once when the route is made."""

    def __init__(self, url: str) -> None:
        self.tools = McpTools(GATEWAY, url, SigV4Auth(boto3.Session()))

    def name(self, target: Target, operation: str) -> str:
        return f"{target}{SEPARATOR}{operation}"

    def call(self, target: Target, operation: str, inputs: dict[str, Any]) -> Any:
        """Call one of the Gateway's tools. A call the Gateway refuses, which the
        MCP client raises as an MCP error, is raised as GatewayRefused."""
        try:
            answer = self.tools.call(self.name(target, operation), inputs)
        except McpError as error:
            raise GatewayRefused(str(error)) from error
        return json.loads(answer)


def from_environment() -> Gateway | None:
    """The Gateway at UNDERCOVER_GATEWAY_URL, read now, or None when it isn't set."""
    url = os.getenv(GATEWAY_URL)
    return Gateway(url) if url else None
