"""The lines that differ between two texts, such as two versions of the claim
agent's instructions or of the improver's recipe, with two lines of context, as
Python's difflib finds them."""

import difflib

from backend.models import Diff, DiffLine, DiffLineKind

CONTEXT = 2
KINDS = {" ": DiffLineKind.CONTEXT, "+": DiffLineKind.ADDED, "-": DiffLineKind.REMOVED}


def diff(old: str, new: str) -> Diff:
    """Return the hunks of lines that differ from the old text to the new, with the
    lines added and removed counted."""
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(), lineterm="", n=CONTEXT
    )
    hunks: list[list[DiffLine]] = []
    # The first two lines name the two texts, which have no names here.
    for line in list(lines)[2:]:
        if line.startswith("@@"):
            hunks.append([])
        else:
            hunks[-1].append(DiffLine(kind=KINDS[line[0]], text=line[1:]))
    changed = [line.kind for hunk in hunks for line in hunk]
    return Diff(
        added=changed.count(DiffLineKind.ADDED),
        removed=changed.count(DiffLineKind.REMOVED),
        hunks=hunks,
    )
