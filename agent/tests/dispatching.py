"""Dispatches the tests work, with claim graphs on a stub model."""

from functools import partial

from langgraph.checkpoint.memory import InMemorySaver

from agent import api, dispatcher, harness
from agent.tests.stubs import agent_on


def new_dispatch(agents=3):
    """Record a new dispatch, as the agent's service does."""
    return api.create_dispatch(agents)


def dispatch(model, saver=None, agents=3):
    """Work a new dispatch with claim graphs on the model, which share a saver as
    they share the database in the service, and return its report lines."""
    saver = saver or InMemorySaver()
    work = partial(harness.work_in_run, new_agent=partial(agent_on, model, saver))
    return dispatcher.work_run(new_dispatch(agents), work)
