"""The command line, and the model and the checkpoint pool it builds."""

from contextlib import nullcontext

import pytest

from agent import __main__ as cli
from agent import harness
from agent.connection import Refused
from backend.tests.versions import add_version


class FakePool:
    """Stands in for psycopg's ConnectionPool, keeping how it was opened and what
    it ran."""

    opened: list["FakePool"] = []

    def __class_getitem__(cls, _):
        return cls

    def __init__(self, conninfo, **settings):
        self.conninfo, self.settings, self.statements = conninfo, settings, []
        self.opened.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def connection(self):
        return nullcontext(self)

    def execute(self, statement):
        self.statements.append(statement)


class FakeSaver:
    """Stands in for LangGraph's PostgresSaver."""

    made: list["FakeSaver"] = []

    def __init__(self, pool):
        self.pool, self.set_up = pool, False
        self.made.append(self)

    def setup(self):
        self.set_up = True


@pytest.fixture
def fakes(monkeypatch):
    """Stand in for psycopg's pool and LangGraph's saver, and keep what is made."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@pooler.example.com/db")
    monkeypatch.setattr(FakePool, "opened", [])
    monkeypatch.setattr(FakeSaver, "made", [])
    monkeypatch.setattr(harness, "ConnectionPool", FakePool)
    monkeypatch.setattr(harness, "PostgresSaver", FakeSaver)


def test_the_checkpoint_pool_settings(fakes):
    with harness.checkpoint_pool():
        [pool] = FakePool.opened
        assert pool.conninfo == "postgresql://u:p@pooler.example.com/db"
        assert (pool.settings["min_size"], pool.settings["max_size"]) == (1, 4)
        assert pool.settings["timeout"] == 120
        kwargs = pool.settings["kwargs"]
        assert (kwargs["autocommit"], kwargs["prepare_threshold"]) == (True, 0)
        assert kwargs["row_factory"] is harness.dict_row
        assert kwargs["options"] == "-c search_path=undercover"
        assert "undercover" in repr(pool.statements[0])
        [saver] = FakeSaver.made
        assert (saver.pool, saver.set_up) == (pool, True)


VERSION = {
    "number": 2,
    "instructions": "Decide the claim.",
    "model": "google/gemini-3.5-flash-lite",
    "reasoning_effort": "minimal",
}


def test_each_claim_graph_has_a_saver_of_its_own(fakes, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    built = []

    def claim_graph(llm, screener, saver, instructions, store):
        built.append((llm, screener, saver, instructions))

    monkeypatch.setattr(harness, "claim_graph", claim_graph)
    with harness.checkpoint_pool() as pool:
        new_agent = harness.claim_graphs(VERSION, None, pool)
        new_agent()
        new_agent()
    [first, second] = built
    assert first[0] is second[0]
    assert first[0].model_name == "google/gemini-3.5-flash-lite"
    assert first[1] is second[1]
    assert (first[1].model_name, first[1].reasoning_effort) == (
        "openai/gpt-6-luna",
        "none",
    )
    assert first[3] == second[3] == "Decide the claim."
    assert first[2] is not second[2]
    assert {first[2].pool, second[2].pool} == {pool}
    assert [saver.set_up for saver in FakeSaver.made] == [True, False, False]


def test_command_line_works_one_claim(monkeypatch, capsys):
    pool = object()
    built = []
    monkeypatch.setattr(cli, "checkpoint_pool", lambda: nullcontext(pool))
    add_version("Version 2's instructions", verdict="kept")

    def claim_graphs(version, kind, on):
        built.append((version["number"], kind, on))
        return lambda: "graph"

    monkeypatch.setattr(cli, "claim_graphs", claim_graphs)
    worked = []
    monkeypatch.setattr(cli, "work_claim", lambda *args: worked.append(args))
    cli.main(["CLM-1001"])
    assert built == [(2, None, pool)]
    assert worked == [("CLM-1001", None, "graph")]

    def refuse(claim_id, run_id, agent):
        raise Refused(409, f"Claim {claim_id} is not waiting")

    monkeypatch.setattr(cli, "work_claim", refuse)
    with pytest.raises(SystemExit) as refused:
        cli.main(["CLM-1003"])
    assert refused.value.code == 1
    assert capsys.readouterr().err == (
        "CLM-1003  not started: 409: Claim CLM-1003 is not waiting\n"
    )


def test_command_line_says_when_the_context_layer_isnt_answering(monkeypatch, capsys):
    monkeypatch.setattr(cli, "checkpoint_pool", lambda: nullcontext(object()))

    def down(version, kind, pool):
        raise ConnectionError("The context layer isn't answering at http://x/mcp")

    monkeypatch.setattr(cli, "claim_graphs", down)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["CLM-1001"])
    assert stopped.value.code == 1
    assert capsys.readouterr().err == (
        "CLM-1001  not started: The context layer isn't answering at http://x/mcp\n"
    )


def test_command_line_needs_a_claim(capsys):
    with pytest.raises(SystemExit):
        cli.main([])
    assert "the following arguments are required: claim_id" in capsys.readouterr().err


def test_the_model_is_the_versions(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    model = harness.model(VERSION | {"reasoning_effort": "medium"})
    assert model.model_name == "google/gemini-3.5-flash-lite"
    assert model.reasoning_effort == "medium"
    assert model.openai_api_base == "https://openrouter.ai/api/v1"
    assert (model.request_timeout, model.max_retries) == (120, 5)


def test_default_sends_no_reasoning_effort(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    model = harness.model(VERSION | {"reasoning_effort": "default"})
    assert model.reasoning_effort is None
