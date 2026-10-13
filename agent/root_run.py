"""Running a LangGraph graph as a root run, wherever it is called."""

import contextvars
from collections.abc import Callable
from typing import Any


def as_root_run[T](run: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Call a graph's run in a fresh context, so it is a root run even inside
    another graph, such as the dispatcher or the improver's tool: Langfuse needs
    that to put it in a session of its own, and a graph run inside another would
    otherwise save into its caller's thread."""
    return contextvars.Context().run(run, *args, **kwargs)
