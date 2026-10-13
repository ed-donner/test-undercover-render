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


PACKAGES = ("agent", "agent.copilot")


def tree_of(module: str) -> ast.Module:
    path = AGENT / f"{module.replace('.', '/')}.py"
    return ast.parse(path.read_text(encoding="utf-8"))


def imports_of(module: str) -> set[str]:
    """The agent's modules a module of the agent imports, by name, the Copilot's
    as copilot.<name>."""
    names: set[str] = set()
    for node in ast.walk(tree_of(module)):
        if isinstance(node, ast.ImportFrom) and node.module in PACKAGES:
            package = node.module.removeprefix("agent").removeprefix(".")
            names |= {f"{package}.{a.name}".removeprefix(".") for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.removeprefix("agent."))
        elif isinstance(node, ast.Import):
            names |= {alias.name.removeprefix("agent.") for alias in node.names}
    return names


def names_from(module: str, imported: str) -> set[str]:
    """The names a module imports from one of the agent's modules."""
    return {
        alias.name
        for node in ast.walk(tree_of(module))
        if isinstance(node, ast.ImportFrom) and node.module == f"agent.{imported}"
        for alias in node.names
    }


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
    assert {"checkpoints", "tool_route"} <= imports_of("harness")
    assert {"gateway", "direct"} & imports_of("harness") == set()
    assert imports_of("tools") & ROUTE_MODULES == {"routes"}
    assert "context_tools" in imports_of("tools")
    for module in (agents_modules() | copilot_modules()) - {"tool_route"}:
        assert {"gateway", "direct"} & imports_of(module) == set(), module
    assert {"gateway", "direct"} <= imports_of("tool_route")
    for module in ("dispatcher", "entrypoint", "improver", "improver_api"):
        assert imports_of(module) & ROUTE_MODULES == set(), module
    assert imports_of("gateway") & agents_modules() == {"routes", "mcp_tools"}
    assert imports_of("direct") & agents_modules() == {"routes", "mcp_tools", "api"}
    assert imports_of("routes") & agents_modules() == set()
    assert imports_of("mcp_tools") & agents_modules() == set()


def test_the_shared_parts_use_only_the_routes_and_the_json():
    for module in ("checkpoints", "context_tools", "agentcore_memory"):
        assert imports_of(module) & agents_modules() <= {"routes", "json_text"}, module


def test_the_apps_terms_and_the_refusals_import_nothing_in_the_agent():
    """So nothing reaches the claim agent's API, or anything else, through them."""
    for module in ("app_terms", "refusals"):
        assert not imports_of(module) & agents_modules(), module


def copilot_modules() -> set[str]:
    return {f"copilot.{path.stem}" for path in (AGENT / "copilot").glob("*.py")}


# The parts of the agent the Copilot may use besides its own: the parts shared
# with the claim agent and the helpers of every part.
SHARED = {
    "app_terms",
    "refusals",
    "checkpoints",
    "tool_route",
    "context_tools",
    "agentcore_memory",
    "agentcore_app",
    "identity",
    "routes",
    "openrouter",
    "json_text",
    "console",
}


def test_the_copilot_uses_only_the_shared_parts_of_the_agent():
    for module in copilot_modules():
        theirs = imports_of(module) - {"connection"}
        assert theirs & agents_modules() <= SHARED, module


def test_only_the_copilots_api_on_the_app_uses_the_connection():
    for module in copilot_modules() - {"copilot.app_api"}:
        assert "connection" not in imports_of(module), module
    assert "call_as" in names_from("copilot.app_api", "connection")


def test_nothing_in_the_claim_agent_imports_the_copilot():
    for module in agents_modules():
        imported = imports_of(module)
        assert {name for name in imported if name.startswith("copilot")} == set()


def test_the_memory_uses_only_agentcore_memory_and_the_claim_agent_uses_it():
    assert imports_of("memory") & agents_modules() == {"agentcore_memory"}
    assert "memory" in imports_of("tools") & imports_of("harness")
    for module in ("improver", "improver_api", "dispatcher", "entrypoint"):
        assert "memory" not in imports_of(module), module


def test_a_handlers_answer_uses_nothing_else_in_the_agent_and_the_harness_uses_it():
    assert imports_of("handler_answer") & agents_modules() == set()
    assert "handler_answer" in imports_of("harness")


def test_the_heartbeat_uses_nothing_else_in_the_agent():
    assert imports_of("heartbeat") & agents_modules() == set()


def test_identity_uses_nothing_else_in_the_agent():
    assert imports_of("identity") & agents_modules() == set()


def test_the_entry_point_hands_the_work_on_and_drives_none_of_it():
    assert {"dispatcher", "heartbeat"} & imports_of("entrypoint") == set()
    assert "work" in imports_of("entrypoint")


def test_the_copilots_memory_uses_only_agentcore_memory():
    theirs = imports_of("copilot.memory") & (agents_modules() | copilot_modules())
    assert theirs == {"agentcore_memory"}
    for module in copilot_modules() - {"copilot.graph", "copilot.turns"}:
        assert "copilot.memory" not in imports_of(module), module
