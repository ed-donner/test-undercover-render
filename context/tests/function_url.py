"""Requests as a Lambda Function URL hands them to the context layer's function."""

from dataclasses import dataclass

FUNCTION = "undercover-context"
HOST = "context.lambda-url.us-east-1.on.aws"


@dataclass
class Context:
    """The context Lambda hands the function with each event."""

    function_name: str = FUNCTION
    function_version: str = "$LATEST"
    invoked_function_arn: str = f"arn:aws:lambda:us-east-1:0:function:{FUNCTION}"
    memory_limit_in_mb: int = 512
    aws_request_id: str = "request-1"
    log_group_name: str = f"/aws/lambda/{FUNCTION}"
    log_stream_name: str = "stream-1"

    def get_remaining_time_in_millis(self) -> int:
        return 30_000


def mcp_request(body: str) -> dict:
    """An MCP request posted to /mcp, as a Function URL hands it to the function,
    with a Function URL's host."""
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/mcp",
        "rawQueryString": "",
        "headers": {
            "host": HOST,
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        "body": body,
        "isBase64Encoded": False,
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "context",
            "domainName": HOST,
            "domainPrefix": "context",
            "http": {
                "method": "POST",
                "path": "/mcp",
                "protocol": "HTTP/1.1",
                "sourceIp": "203.0.113.7",
                "userAgent": "test",
            },
            "requestId": "request-1",
            "routeKey": "$default",
            "stage": "$default",
            "time": "07/Oct/2026:12:00:00 +0000",
            "timeEpoch": 1791460800000,
        },
    }
