"""The policy wording and the claims manual: their numbered sections' headings,
which the claim agent's instructions end with, and the manual's version."""

import re

from sqlalchemy import Connection, select

from backend.database import CLAIMS_MANUAL, documents

HEADING = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)


def titles(db: Connection) -> dict[str, str]:
    """Return the title of each document, the policy wording first."""
    query = select(documents.c.name, documents.c.title).order_by(documents.c.position)
    return {row["name"]: row["title"] for row in db.execute(query).mappings()}


def headings(db: Connection, document: str) -> list[tuple[int, str]]:
    """Return the number and title of each of a document's sections."""
    query = select(documents.c.text).where(documents.c.name == document)
    text = db.execute(query).scalar_one()
    return [(int(number), title) for number, title in HEADING.findall(text)]


def contents(db: Connection) -> str:
    """List the numbered sections of both documents, without their text."""
    parts = []
    for document, title in titles(db).items():
        lines = [f"{number}. {heading}" for number, heading in headings(db, document)]
        parts.append(f"## Contents of the {title.lower()}\n\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


def manual_version(db: Connection) -> str:
    """Return the version of the claims manual in force."""
    query = select(documents.c.version).where(documents.c.name == CLAIMS_MANUAL)
    return db.execute(query).scalar_one()
