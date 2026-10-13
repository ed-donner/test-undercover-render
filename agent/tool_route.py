"""The route the agents' tools take to the context layer, and the claim agent's to
the app: the Gateway when UNDERCOVER_GATEWAY_URL is set, or else the direct route.
It is the one module that knows both."""

from agent import direct, gateway
from agent.routes import Route


def from_environment() -> Route:
    """The Gateway when the environment names one, read now, or else the direct
    route."""
    return gateway.from_environment() or direct.from_environment()
