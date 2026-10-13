"""The context layer's files that seeding reads: the plans, and each document's
body and version. Only seeding reads them, so nothing reads context/ when the app
is imported or for a request, and the app's package needs no context/."""

from pathlib import Path
from typing import Any, NamedTuple

import yaml

CONTEXT = Path(__file__).resolve().parent.parent / "context"
# A document's front matter, its source and version, sits between two lines of ---.
FRONT_MATTER = "---\n"


class Document(NamedTuple):
    """A document's body, without its front matter, and its version."""

    text: str
    version: str


def read(file: str) -> str:
    return (CONTEXT / file).read_text(encoding="utf-8")


def plans() -> dict[str, Any]:
    """The plans, the benefits the deductible applies to and the add-ons, without
    the file's source."""
    rules = yaml.safe_load(read("plans.yaml"))
    del rules["source"]
    return rules


def document(name: str) -> Document:
    """A document's body and the version its front matter gives."""
    _, front, body = read(f"{name}.md").split(FRONT_MATTER, 2)
    return Document(body.lstrip("\n"), yaml.safe_load(front)["version"])
