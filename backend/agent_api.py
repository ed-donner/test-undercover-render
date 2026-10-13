"""The claim agent's own API document: the OpenAPI document of the eight operations
its tools call, which the Gateway turns into tools."""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute, iter_route_contexts

OPERATIONS = {
    "get_claim",
    "get_policy",
    "get_claim_history",
    "search_documents",
    "read_section",
    "calculate_payout",
    "record_decision",
    "pay_claim",
}


def document(app: FastAPI) -> dict[str, Any]:
    """Build the document of the claim agent's operations from the app's own routes,
    with no servers, which the deployment adds, and no security schemes, which a
    Gateway's OpenAPI target doesn't support: its credential provider sends the
    key instead."""
    routes = [
        context
        for context in iter_route_contexts(app.routes)
        if isinstance(context.route, APIRoute)
        and context.route.operation_id in OPERATIONS
    ]
    agents = get_openapi(
        title=f"{app.title} claim agent", version=app.version, routes=routes
    )
    del agents["components"]["securitySchemes"]
    for operations in agents["paths"].values():
        for operation in operations.values():
            del operation["security"]
    return agents
