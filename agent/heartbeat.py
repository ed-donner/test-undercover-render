"""The agent's word to the app that it is still working, every minute while a piece of
its work goes on."""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

# How often the agent tells the app, in seconds: well within the five minutes the
# app waits before it counts work as stopped.
INTERVAL = 60.0

log = logging.getLogger(__name__)


@contextmanager
def beating(tell: Callable[[], object]) -> Iterator[None]:
    """Call tell() every INTERVAL seconds, on a thread of its own, while the block
    runs, and never after it ends. A call that fails is logged and never stops the
    work."""
    stopped = threading.Event()

    def beat() -> None:
        while not stopped.wait(INTERVAL):
            try:
                tell()
            except Exception as error:  # the work goes on without its heartbeat
                log.warning("The heartbeat failed: %s", error)

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()
