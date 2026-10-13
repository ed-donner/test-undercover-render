"""AgentCore Memory as a LangGraph store, which both agents' memories use: the store
for a Memory's id, in the AWS CLI's region, and what it raises when AgentCore can't
be reached or refuses a call."""

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from langgraph.store.base import BaseStore
from langgraph_checkpoint_aws import AgentCoreMemoryStore

UNREACHABLE = (BotoCoreError, ClientError)


def store_at(memory_id: str) -> BaseStore:
    """The AgentCore Memory with this id, in the AWS CLI's region."""
    region = boto3.Session().region_name
    return AgentCoreMemoryStore(memory_id=memory_id, region_name=region)
