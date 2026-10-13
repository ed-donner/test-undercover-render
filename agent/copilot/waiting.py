"""Waiting for a dispatch or an evaluation the Copilot started, in code, with no
model call: the run read from the app with the handler's sign-in every POLL
seconds until it isn't running, for up to WAIT seconds, then how it went."""

import time
from typing import Any

from agent.app_terms import DISPATCH, EVALUATION, RUNNING, STOPPED
from agent.copilot import app_api
from agent.copilot.needs_a_handler import needs_a_handler

POLL = 5
WAIT = 15 * 60
# Where a handler follows a run that is still going.
PAGES = {DISPATCH: "the queue page", EVALUATION: "the Scoreboard"}
STILL_GOING = "Still going after {minutes} minutes. Follow it on {page}."


def wait_for(sign_in: str, run_id: str) -> dict[str, Any]:
    """The run once it has finished or stopped, or as it stands, still running,
    after WAIT."""
    deadline = time.monotonic() + WAIT
    while (run := app_api.get_run(sign_in, run_id))["status"] == RUNNING:
        if time.monotonic() + POLL > deadline:
            break
        time.sleep(POLL)
    return run


def measures_of(sign_in: str, run_id: str) -> dict[str, Any]:
    """An evaluation's measures, as the Scoreboard scores it."""
    evaluations = app_api.list_evaluations(sign_in)
    return next(e for e in evaluations if e["run_id"] == run_id)["measures"]


def how_it_went(sign_in: str, run: dict[str, Any]) -> dict[str, Any]:
    """How a run went: a finished dispatch's summary, time and cost and what needs
    a handler, a finished evaluation's measures, why a run stopped, or where to
    follow one still going."""
    went = {"kind": run["kind"], "number": run["number"], "status": run["status"]}
    if run["status"] == RUNNING:
        page = PAGES[run["kind"]]
        return went | {"note": STILL_GOING.format(minutes=round(WAIT / 60), page=page)}
    if run["status"] == STOPPED:
        return went | {"stopped_because": run["stopped_because"]}
    if run["kind"] == DISPATCH:
        queue = app_api.list_claims(sign_in)
        return went | {
            "summary": run["summary"],
            "seconds": run["seconds"],
            "model_cost": run["model_cost"],
            "needs_a_handler": needs_a_handler(queue),
        }
    return went | {"measures": measures_of(sign_in, run["run_id"])}
