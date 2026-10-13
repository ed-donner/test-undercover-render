"""A small agent on AgentCore Runtime.

chat: answer a question, with one tool
start and resume: propose a payout for a claim, pause for a handler, and decide again
with the handler's note, in any session, from the claim's thread in Supabase
hello: nothing, to time how long a session takes to start
"""

from functools import cache
from typing import TypedDict

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from model.load import load_model, secret

app = BedrockAgentCoreApp()

CLAIM = """CLM-9001: a flight from Chicago to Boston was canceled, and the next flight left
the following evening. The traveler asks for $1,180 for the delay, with four receipts:
a hotel night for $520, meals for $180, a taxi for $240 and a taxi for $240. The plan
pays reasonable expenses after a delay of 12 hours or more, up to $1,500."""

# The transaction pooler takes no prepared statements, and the lab's tables have a schema of their own
SETTINGS = {
    "autocommit": True,
    "prepare_threshold": None,
    "row_factory": dict_row,
    "options": "-c search_path=lab",
}


class Claim(TypedDict, total=False):
    claim: str
    proposal: str
    note: str
    decision: str


@tool
def add_numbers(a: int, b: int) -> int:
    """Return the sum of two numbers"""
    return a + b


@cache
def model():
    """The model, made on the first request."""
    return load_model()


def propose(state: Claim) -> Claim:
    """Propose a payout for the claim."""
    prompt = f"Propose a payout for this claim in one or two sentences.\n\n{state['claim']}"
    return {"proposal": model().invoke(prompt).text}


def approval(state: Claim) -> Claim:
    """Pause until a handler reviews the proposal, then keep the handler's note."""
    return {"note": interrupt({"proposal": state["proposal"]})}


def revise(state: Claim) -> Claim:
    """Decide again with the handler's note."""
    prompt = f"""{state['claim']}

You proposed: {state['proposal']}
A senior handler sent it back with this note: {state['note']}
Give your revised payout in one or two sentences."""
    return {"decision": model().invoke(prompt).text}


@cache
def claim_graph():
    """The claim graph, made on the first request, saving its progress in Supabase."""
    pool = ConnectionPool(secret("DatabaseUrl"), min_size=1, max_size=2, kwargs=SETTINGS, open=True)
    with pool.connection() as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS lab")
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()

    builder = StateGraph(Claim)
    builder.add_node("propose", propose)
    builder.add_node("approval", approval)
    builder.add_node("revise", revise)
    builder.add_edge(START, "propose")
    builder.add_edge("propose", "approval")
    builder.add_edge("approval", "revise")
    builder.add_edge("revise", END)
    return builder.compile(checkpointer=checkpointer)


def chat(prompt: str) -> dict:
    """Answer a question with the template's agent and its tool."""
    system_prompt = "You are a helpful assistant. Use tools when appropriate."
    agent = create_agent(model(), tools=[add_numbers], system_prompt=system_prompt)
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    return {"answer": result["messages"][-1].text}


def work_claim(payload: dict) -> dict:
    """Start the claim on a thread, or resume it with a handler's note."""
    config = {"configurable": {"thread_id": payload["thread_id"]}}
    start = {"claim": CLAIM} if payload["action"] == "start" else Command(resume=payload["note"])
    state = claim_graph().invoke(start, config, durability="sync")
    return {"proposal": state["proposal"], "decision": state.get("decision"), "paused": "__interrupt__" in state}


@app.entrypoint
def invoke(payload, context):
    """Answer one request, saying which session answered it."""
    reply = {}
    if payload["action"] == "chat":
        reply = chat(payload["prompt"])
    elif payload["action"] in ("start", "resume"):
        reply = work_claim(payload)
    return reply | {"session": context.session_id}


if __name__ == "__main__":
    app.run()
