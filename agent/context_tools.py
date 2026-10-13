"""The context layer's seven lookups, which both agents have: each calls the context
layer's tool of the same name on the route in the agent's context, and gives the
model the answer and, as its artifact, a lookup step naming what was looked up and
the files the answer came from."""

from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from langchain.tools import ToolRuntime, tool
from pydantic import StringConstraints

from agent.json_text import as_json
from agent.routes import Route, Target

# A search needs a word or phrase to look for.
Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
DocumentName = Literal["policy_wording", "claims_manual"]
RecordName = Literal["claim", "policy", "previous_claim"]
PlanName = Literal["economy", "premium", "first"]
# The context files an answer came from, each with its system, owner and review
# date, and the lookup step a tool gives as its artifact.
Sources = list[dict[str, str]]
Lookup = tuple[Literal["lookup"], str, Sources]


# Checkable at run time, since an agent's context is validated when a tool reads it.
@runtime_checkable
class RouteContext(Protocol):
    """An agent's context, which holds the route its tools take."""

    route: Route


def on_context(
    runtime: ToolRuntime[RouteContext], operation: str, **inputs: Any
) -> Any:
    """Call one of the context layer's tools on the agent's route."""
    return runtime.context.route.call(Target.CONTEXT, operation, inputs)


def looked_up(answer: dict[str, Any], what: str) -> tuple[str, Lookup]:
    """A context layer's answer for the model, and a lookup step that says what
    was looked up and the files the answer came from."""
    return as_json(answer), ("lookup", what, answer["sources"])


@tool(response_format="content_and_artifact")
def lookup_term(term: str, runtime: ToolRuntime[RouteContext]) -> tuple[str, Lookup]:
    """Look up a term the policy wording defines: its definition and sections."""
    answer = on_context(runtime, "lookup_term", term=term)
    return looked_up(answer, f'Term "{term}"')


@tool(response_format="content_and_artifact")
def describe_fields(
    record: RecordName, runtime: ToolRuntime[RouteContext]
) -> tuple[str, Lookup]:
    """Describe a record you read and the meaning of each of its fields."""
    answer = on_context(runtime, "describe_fields", record=record)
    return looked_up(answer, f"Fields of a {record.replace('_', ' ')}")


@tool(response_format="content_and_artifact")
def get_plan(plan: PlanName, runtime: ToolRuntime[RouteContext]) -> tuple[str, Lookup]:
    """Get a plan's limits, waiting periods, deductible and the add-ons."""
    return looked_up(on_context(runtime, "get_plan", plan=plan), f"Plan: {plan}")


@tool(response_format="content_and_artifact")
def get_claim_rules(runtime: ToolRuntime[RouteContext]) -> tuple[str, Lookup]:
    """Get the rules claims operations applies to every claim."""
    return looked_up(on_context(runtime, "get_claim_rules"), "The claim rules")


@tool(response_format="content_and_artifact")
def search_reference_data(
    query: Query, runtime: ToolRuntime[RouteContext]
) -> tuple[str, Lookup]:
    """Find outside facts, such as storms, strikes and prices, with every word."""
    answer = on_context(runtime, "search_reference_data", query=query)
    return looked_up(answer, f'Reference data: "{query}"')


@tool(response_format="content_and_artifact")
def search_documents(
    query: Query, runtime: ToolRuntime[RouteContext]
) -> tuple[str, Lookup]:
    """Find the sections of the wording and the manual containing one word or phrase."""
    answer = on_context(runtime, "search_documents", query=query)
    return looked_up(answer, f'Documents: "{query}"')


@tool(response_format="content_and_artifact")
def read_section(
    document: DocumentName, number: int, runtime: ToolRuntime[RouteContext]
) -> tuple[str, Lookup]:
    """Read one section of the policy wording or the claims manual in full."""
    section = on_context(runtime, "read_section", document=document, number=number)
    read = f"{section['document_title']}, section {number}: {section['title']}"
    return looked_up(section, read)


CONTEXT_TOOLS = [
    lookup_term,
    describe_fields,
    get_plan,
    get_claim_rules,
    search_reference_data,
    search_documents,
    read_section,
]
