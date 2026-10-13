"""Runs the tests work, which a handler starts and the app creates, with claim graphs
on a stub model."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent import dispatcher, harness
from agent.tests.stubs import agent_on
from backend.dependencies import API_KEY_HEADER
from backend.main import app
from backend.tests.run_requests import create_dispatch, create_evaluation


@contextmanager
def the_app() -> Iterator[TestClient]:
    """The app, called with the agent's key, as the agent and the backend's tests
    call it, and closed once the block's calls are done."""
    headers = {API_KEY_HEADER: os.environ["UNDERCOVER_API_KEY"]}
    with TestClient(app, headers=headers) as caller:
        yield caller


def new_dispatch(agents=3):
    """Start a dispatch as a handler does, which the app creates, and return it as
    the agent reads it."""
    with the_app() as caller:
        return create_dispatch(caller, agents).json()


def new_evaluation(evaluation_set="held_out", tiny=True, agents=5):
    """Start an evaluation as a handler does, which the app creates with its copies,
    and return it as the agent reads it."""
    with the_app() as caller:
        return create_evaluation(caller, evaluation_set, tiny, agents).json()


def dispatch(model, saver=None, agents=3):
    """Work a new dispatch with claim graphs on the model, which share a saver as
    they share the database in the agent, and return its report lines."""
    saver = saver or InMemorySaver()
    work = partial(harness.work_in_run, new_agent=partial(agent_on, model, saver))
    return dispatcher.work_run(new_dispatch(agents), work)
