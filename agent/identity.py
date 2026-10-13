"""AgentCore Identity, where the agent's secrets are kept on Runtime. The deployment
names the credential provider of each secret in a setting
AGENTCORE_CREDENTIAL_<NAME>_NAME, and the agent fetches each one's value into the
setting <NAME>, where .env puts it on the laptop."""

import os

from bedrock_agentcore.identity.auth import requires_api_key

PREFIX = "AGENTCORE_CREDENTIAL_"
SUFFIX = "_NAME"


def providers() -> dict[str, str]:
    """The credentials the deployment named, each by the setting its value goes
    into, with its provider in Identity."""
    return {
        name.removeprefix(PREFIX).removesuffix(SUFFIX): provider
        for name, provider in os.environ.items()
        if name.startswith(PREFIX) and name.endswith(SUFFIX)
    }


def on_runtime() -> bool:
    """Say whether the agent runs on AgentCore Runtime: the deployment named its
    credentials."""
    return bool(providers())


def fetch_credentials() -> None:
    """Fetch each credential's value from Identity into its setting. Identity reads
    the token Runtime sends with each request, so this runs while the agent handles
    one."""
    for setting, provider in providers().items():
        fetch = requires_api_key(provider_name=provider)(lambda api_key: api_key)
        os.environ[setting] = fetch()
