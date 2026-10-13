"""The context layer's MCP server: its seven lookups as read-only tools over
streamable HTTP at /mcp, stateless and answering in JSON. handler is its entry point
on AWS Lambda, behind a Function URL."""

from typing import Annotated, Any

from mangum import Mangum
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import StringConstraints

from context import files

NAME = "undercover-context"
# The port the context layer serves on the laptop, at /mcp.
PORT = 8006
# A search needs a word or phrase to look for.
Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
READ_ONLY = ToolAnnotations(readOnlyHint=True)
# A Function URL's host would be refused as a DNS rebinding attack, and the
# Function URL's IAM auth guards the server there.
ON_LAMBDA = TransportSecuritySettings(enable_dns_rebinding_protection=False)


def build_server(security: TransportSecuritySettings | None = None) -> FastMCP:
    """Make the server with its seven tools, on the laptop's port, with FastMCP's
    protection for a local host unless the security given says otherwise."""
    server = FastMCP(
        NAME,
        port=PORT,
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )

    @server.tool(annotations=READ_ONLY)
    def lookup_term(term: str) -> dict[str, Any]:
        """Look up a term the policy wording defines: its definition and sections."""
        return files.lookup_term(term)

    @server.tool(annotations=READ_ONLY)
    def describe_fields(record: files.RecordName) -> dict[str, Any]:
        """Describe a record the claim agent reads and the meaning of its fields."""
        return files.describe_fields(record)

    @server.tool(annotations=READ_ONLY)
    def get_plan(plan: files.PlanName) -> dict[str, Any]:
        """Get a plan's limits, waiting periods, deductible and the add-ons."""
        return files.get_plan(plan)

    @server.tool(annotations=READ_ONLY)
    def get_claim_rules() -> dict[str, Any]:
        """Get the rules claims operations applies to every claim."""
        return files.get_claim_rules()

    @server.tool(annotations=READ_ONLY)
    def search_reference_data(query: Query) -> dict[str, Any]:
        """Find outside facts, such as storms, strikes and prices, with every word."""
        return files.search_reference_data(query)

    @server.tool(annotations=READ_ONLY)
    def search_documents(query: Query) -> dict[str, Any]:
        """Find sections of the wording and the manual containing a word or phrase."""
        return files.search_documents(query)

    @server.tool(annotations=READ_ONLY)
    def read_section(document: files.DocumentName, number: int) -> dict[str, Any]:
        """Read one section of the policy wording or the claims manual in full."""
        return files.read_section(document, number)

    return server


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda's entry point: a fresh server for each request, since Mangum runs
    an app's startup and shutdown around every request and a server's session
    manager runs only once."""
    app = build_server(ON_LAMBDA).streamable_http_app()
    return Mangum(app, lifespan="auto")(event, context)
