"""Asking an AgentCore app, the agent or the Copilot, to take work the app has
recorded: commit it first, so the app it asks sees it, and undo it when the app
didn't take it."""

from collections.abc import Callable

from sqlalchemy import Connection

from backend.runtime_calls import NotTaken


def commit_and_ask(
    db: Connection, ask: Callable[[], None], undo: Callable[[str], object]
) -> None:
    """Commit what the app did for the work, then ask for it to be taken. When it
    wasn't, undo it with the reason and commit the undo before passing on the
    refusal; when it may have been, change nothing."""
    db.commit()
    try:
        ask()
    except NotTaken as refusal:
        undo(refusal.detail)
        db.commit()
        raise
