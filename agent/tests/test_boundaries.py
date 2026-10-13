"""What each part of the agent can reach: the claim agent's API holds nothing of
the rounds, the scores or the settings, and the improver and the claim agent don't
import each other's parts."""

import ast
import inspect
from pathlib import Path

from agent import api
from backend.main import app

AGENT = Path(__file__).parent.parent
OUT_OF_REACH = (
    "/api/rounds",
    "/api/improvement",
    "/api/configuration",
    "/api/settings",
)


def operations_out_of_reach() -> set[str]:
    operations = {"list_evaluations", "get_evaluation"}
    for path, methods in app.openapi()["paths"].items():
        if path.startswith(OUT_OF_REACH):
            operations |= {op["operationId"] for op in methods.values()}
    return operations


def imports_of(module: str) -> set[str]:
    """The agent's modules a module of the agent imports, by name."""
    tree = ast.parse((AGENT / f"{module}.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "agent":
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.removeprefix("agent."))
        elif isinstance(node, ast.Import):
            names |= {alias.name.removeprefix("agent.") for alias in node.names}
    return names


def test_the_claim_agents_api_has_no_way_to_the_rounds_scores_or_settings():
    functions = {name for name, _ in inspect.getmembers(api, inspect.isfunction)}
    assert operations_out_of_reach() & functions == set()
    source = inspect.getsource(api)
    assert [path for path in OUT_OF_REACH if path.removeprefix("/api") in source] == []


def test_the_claim_agent_doesnt_import_the_improvers_api():
    for module in ("tools", "harness"):
        assert "improver_api" not in imports_of(module)


def test_the_improver_doesnt_import_the_claim_agents_harness_or_dispatcher():
    assert {"harness", "dispatcher"} & imports_of("improver") == set()


def agents_modules() -> set[str]:
    return {path.stem for path in AGENT.glob("*.py")}


def test_the_check_uses_nothing_else_in_the_agent_and_the_harness_uses_it():
    assert imports_of("screening") & agents_modules() == set()
    assert "screening" in imports_of("harness")


ROUTE_MODULES = {"routes", "gateway", "direct", "mcp_tools"}


def test_the_routes_and_who_uses_them():
    assert {"routes", "gateway", "direct"} <= imports_of("harness")
    assert imports_of("tools") & ROUTE_MODULES == {"routes"}
    for module in agents_modules() - {"harness", "__main__"}:
        assert {"gateway", "direct"} & imports_of(module) == set(), module
    for module in ("dispatcher", "service", "improver", "improver_api"):
        assert imports_of(module) & ROUTE_MODULES == set(), module
    assert imports_of("gateway") & agents_modules() == {"routes", "mcp_tools"}
    assert imports_of("direct") & agents_modules() == {"routes", "mcp_tools", "api"}
    assert imports_of("routes") & agents_modules() == set()
    assert imports_of("mcp_tools") & agents_modules() == set()


def test_the_memory_uses_nothing_else_in_the_agent_and_the_claim_agent_uses_it():
    assert imports_of("memory") & agents_modules() == set()
    assert "memory" in imports_of("tools") & imports_of("harness")
    for module in ("improver", "improver_api", "dispatcher", "service"):
        assert "memory" not in imports_of(module), module
