"""How the tests' stand-in for the agent on the laptop answers: it takes the work, or
it doesn't, since it can't be reached, times out, refuses or gives an error
answer."""

import httpx


def accepting(request):
    return httpx.Response(200, json={"accepted": True})


def unreachable(request):
    raise httpx.ConnectError("Connection refused")


def slow(request):
    raise httpx.ReadTimeout("Timed out")


def refusing_with(reason):
    """Refuse the work with a reason."""
    return lambda request: httpx.Response(200, json={"refused": reason})


refusing = refusing_with("Claim CLM-1002 isn't paused for a handler")


def broken(request):
    return httpx.Response(500, json={"error": "The agent couldn't get ready"})
