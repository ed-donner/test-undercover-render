"""The console, where the agent's entry points print report lines, and how a line
says what went wrong."""

import logging
import sys


def show_reports() -> None:
    """Print the report lines as the agent works."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout)
    logging.getLogger("agent").setLevel(logging.INFO)


def describe(error: BaseException) -> str:
    """Say in one line what went wrong."""
    lines = str(error).splitlines()
    return f"{type(error).__name__}: {lines[0]}" if lines else type(error).__name__
