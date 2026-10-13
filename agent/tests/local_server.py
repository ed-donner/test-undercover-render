"""Serving an app on a free local port in a thread of its own, as the tests serve
the context layer and the stand-in Gateway."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from starlette.types import ASGIApp

HOST = "127.0.0.1"
START_UP = 10


@contextmanager
def serving(app: ASGIApp) -> Iterator[str]:
    """Serve an ASGI app on a free local port until the block ends, and give its
    address."""
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
        thread.start()
        deadline = time.monotonic() + START_UP
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("The local server didn't start")
            time.sleep(0.01)
        try:
            yield f"http://{HOST}:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join()
