"""The model through OpenRouter, with its key from AgentCore Identity."""

import os

from bedrock_agentcore.identity.auth import requires_api_key
from langchain_openai import ChatOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openai/gpt-6-luna"


def secret(name: str) -> str:
    """One of the project's credentials, from AgentCore Identity when deployed, or from
    .env.local under agentcore dev."""
    if os.getenv("LOCAL_DEV") == "1":
        return os.environ[f"AGENTCORE_CREDENTIAL_{name.upper()}"]

    @requires_api_key(provider_name=os.environ[f"AGENTCORE_CREDENTIAL_{name.upper()}_NAME"])
    def fetch(api_key: str) -> str:
        return api_key

    return fetch()


def load_model() -> ChatOpenAI:
    """The model through OpenRouter, which speaks the OpenAI API."""
    return ChatOpenAI(
        model=MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=secret("OpenRouter"),
        reasoning_effort="low",
        timeout=120,
        max_retries=5,
    )
