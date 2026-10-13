"""Claims the tests hold for a handler's sign-off, paused or stopped short of the
pause, and resume through the agent's AgentCore app."""

from langgraph.checkpoint.memory import InMemorySaver

from agent import harness
from agent.tests import invoking
from agent.tests.records import claim_of
from agent.tests.stubs import agent_on, approve, stub

# The channel LangGraph saves an interrupt on, which the claim graph's pause writes.
INTERRUPT = "__interrupt__"


def state_of(agent, client, claim_id):
    """The claim graph's saved state on the claim's thread."""
    return agent.graph.get_state(harness.thread_of(claim_of(client, claim_id)))


def hold(claim_id="CLM-1003", payout=3750.0, saver=None, **given):
    """Work a claim to an approval over the limit, held for sign-off, and return its
    claim agent."""
    agent = agent_on(stub(*approve(claim_id, payout)), saver, **given)
    harness.work_claim(claim_id, None, agent)
    return agent


class StopAtThePause(InMemorySaver):
    """Stops as the pause's interrupt is saved, once: the decision and the step that
    recorded it are saved, and the pause never ran, as when the process stops in
    between."""

    stopped = False

    def put_writes(self, config, writes, task_id, task_path=""):
        if not self.stopped and any(channel == INTERRUPT for channel, _ in writes):
            self.stopped = True
            raise KeyboardInterrupt
        super().put_writes(config, writes, task_id, task_path)


def resume_claim(agent, claim_id):
    """Ask the agent to resume a claim, as the app does, and wait for the resume."""
    return agent.invoke(invoking.resume_claim(claim_id))
