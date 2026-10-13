"""How the tests' stand-ins for the agent and the Copilot on the laptop answer: they
take the work, or they don't, since they can't be reached, time out, refuse or give
an error answer."""

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


def raising(error):
    """Answer by raising the error, as httpx does when a request fails."""

    def answer(request):
        raise error

    return answer


def answering(status, body):
    """Answer with the status and body given."""
    return lambda request: httpx.Response(status, content=body)
