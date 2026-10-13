from agent.json_text import as_json
from agent.tools import CLAIM_TOOLS


def operations(client):
    """Return the operation ids of the backend's API."""
    paths = client.get("/openapi.json").json()["paths"].values()
    return {operation["operationId"] for path in paths for operation in path.values()}


def test_claim_tools_are_named_after_backend_operations(client):
    names = [t.name for t in CLAIM_TOOLS]
    assert names == [
        "get_claim",
        "get_policy",
        "get_claim_history",
        "search_documents",
        "read_section",
        "calculate_payout",
        "record_decision",
    ]
    assert set(names) <= operations(client)


def test_a_claim_agent_can_only_act_on_its_own_claim():
    assert all("claim_id" not in t.args for t in CLAIM_TOOLS)


def test_the_agent_writes_json_with_characters_as_themselves():
    section = {"title": "Policy wording §2", "note": "the plan’s limit"}
    assert as_json(section) == (
        '{"title": "Policy wording §2", "note": "the plan’s limit"}'
    )
