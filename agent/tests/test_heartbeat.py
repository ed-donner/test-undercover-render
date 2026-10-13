"""The agent's heartbeat: it tells the app every interval while its work goes on."""

import time

from agent import heartbeat


def test_it_tells_each_interval_while_its_block_runs_and_never_after(monkeypatch):
    monkeypatch.setattr(heartbeat, "INTERVAL", 0.01)
    told = []
    with heartbeat.beating(lambda: told.append(time.monotonic())):
        time.sleep(0.1)
    beats = len(told)
    assert beats >= 3
    time.sleep(0.05)
    assert len(told) == beats


def test_none_before_the_first_interval():
    told = []
    with heartbeat.beating(lambda: told.append(1)):
        pass
    assert told == []


def test_a_failing_call_is_logged_and_the_work_goes_on(monkeypatch, caplog):
    monkeypatch.setattr(heartbeat, "INTERVAL", 0.01)

    tried = []

    def unanswered():
        tried.append(1)
        raise RuntimeError("The app isn't answering")

    with heartbeat.beating(unanswered):
        time.sleep(0.1)
    assert len(tried) >= 3
    failed = [m for m in caplog.messages if m.startswith("The heartbeat failed")]
    assert failed == ["The heartbeat failed: The app isn't answering"] * len(tried)
