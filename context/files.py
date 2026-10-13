"""The context layer's seven files, read once when the process starts, and the
lookups on them. Every answer holds its sources: the files its content came from,
each with that file's system, owner and review date, so a search that finds
nothing has none. It reads only from its own folder and writes nothing."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

FOLDER = Path(__file__).parent
DocumentName = Literal["policy_wording", "claims_manual"]
RecordName = Literal["claim", "policy", "previous_claim"]
PlanName = Literal["economy", "premium", "first"]
TITLES: dict[DocumentName, str] = {
    "policy_wording": "Policy wording",
    "claims_manual": "Claims manual",
}
GLOSSARY = "glossary.yaml"
DATA_DICTIONARY = "data_dictionary.yaml"
PLANS = "plans.yaml"
CLAIM_RULES = "claim_rules.yaml"
REFERENCE_DATA = "reference_data.yaml"
# A document's front matter, its source and version, sits between two lines of ---.
FRONT_MATTER = "---\n"
HEADING = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)
PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
UNKNOWN_TERM = 'The glossary doesn\'t define "{term}". These are the terms it does.'


class Refused(Exception):
    """A lookup the context layer refuses, with its reason."""


@dataclass(frozen=True)
class Section:
    """One numbered section of a document, tagged with its document."""

    document: DocumentName
    number: int
    title: str
    text: str


@dataclass(frozen=True)
class Document:
    """A document's sections, its version and its file's source."""

    name: DocumentName
    version: str
    source: dict[str, str]
    sections: dict[int, Section]


def file_source(file: str, source: dict[str, str]) -> dict[str, str]:
    """A file's source as an answer names it: the file, and its system, owner and
    review date."""
    return {"file": file} | source


def read_yaml(file: str) -> dict[str, Any]:
    """Read one of the YAML files, with its source."""
    data = yaml.safe_load((FOLDER / file).read_text(encoding="utf-8"))
    return data | {"source": file_source(file, data["source"])}


def split_sections(name: DocumentName, body: str) -> dict[int, Section]:
    """Split a document's body at its numbered headings into its sections."""
    headings = list(HEADING.finditer(body))
    ends = [heading.start() for heading in headings[1:]] + [len(body)]
    return {
        int(heading[1]): Section(
            name, int(heading[1]), heading[2], body[heading.end() : end].strip()
        )
        for heading, end in zip(headings, ends, strict=True)
    }


def read_document(name: DocumentName) -> Document:
    """Read a document, its front matter apart from its sections."""
    file = f"{name}.md"
    text = (FOLDER / file).read_text(encoding="utf-8")
    _, front, body = text.split(FRONT_MATTER, 2)
    about = yaml.safe_load(front)
    source = file_source(file, about["source"])
    return Document(name, about["version"], source, split_sections(name, body))


FILES = {
    file: read_yaml(file)
    for file in (GLOSSARY, DATA_DICTIONARY, PLANS, CLAIM_RULES, REFERENCE_DATA)
}
DOCUMENTS = {name: read_document(name) for name in TITLES}


def sources_of(file: str) -> list[dict[str, str]]:
    """An answer's sources when it comes from one of the YAML files."""
    return [FILES[file]["source"]]


def lookup_term(term: str) -> dict[str, Any]:
    """A term the policy wording defines, matched whatever its case, with its
    definition and the sections it comes from, or, for a term it doesn't define,
    the terms it does."""
    glossary = FILES[GLOSSARY]
    for entry in glossary["terms"]:
        if entry["term"].lower() == term.strip().lower():
            return entry | {"sources": sources_of(GLOSSARY)}
    return {
        "answer": UNKNOWN_TERM.format(term=term),
        "terms": [entry["term"] for entry in glossary["terms"]],
        "sources": sources_of(GLOSSARY),
    }


def describe_fields(record: RecordName) -> dict[str, Any]:
    """A record's description and the meaning of each of its fields."""
    [found] = [r for r in FILES[DATA_DICTIONARY]["records"] if r["record"] == record]
    return found | {"sources": sources_of(DATA_DICTIONARY)}


def get_plan(plan: PlanName) -> dict[str, Any]:
    """A plan's limits, waiting periods and deductible, the benefits the deductible
    applies to, and the add-ons."""
    plans = FILES[PLANS]
    [found] = [p for p in plans["plans"] if p["plan"] == plan]
    return {
        "plan": found,
        "deductible_applies_to": plans["deductible_applies_to"],
        "add_ons": plans["add_ons"],
        "sources": sources_of(PLANS),
    }


def get_claim_rules() -> dict[str, Any]:
    """The rules claims operations applies to every claim."""
    return {"rules": FILES[CLAIM_RULES]["rules"], "sources": sources_of(CLAIM_RULES)}


def search_reference_data(query: str) -> dict[str, Any]:
    """The outside facts that contain every word of the query, whatever its case,
    each with its topic."""
    words = query.lower().split()
    facts = [
        {"topic": topic["topic"], "fact": fact}
        for topic in FILES[REFERENCE_DATA]["topics"]
        for fact in topic["facts"]
        if all(word in fact.lower() for word in words)
    ]
    return {"facts": facts, "sources": sources_of(REFERENCE_DATA) if facts else []}


def search_documents(query: str) -> dict[str, Any]:
    """The sections of the wording and the manual whose title or text contains the
    query, ignoring case, with the paragraphs that mention it, each naming its
    file."""
    wanted = query.lower()
    sections, sources = [], []
    for document in DOCUMENTS.values():
        for section in document.sections.values():
            paragraphs = PARAGRAPH_BREAK.split(section.text)
            excerpts = [p for p in paragraphs if wanted in p.lower()]
            if excerpts or wanted in section.title.lower():
                sections.append(
                    {
                        "document": document.name,
                        "file": document.source["file"],
                        "number": section.number,
                        "title": section.title,
                        "excerpts": excerpts,
                    }
                )
                if document.source not in sources:
                    sources.append(document.source)
    return {"sections": sections, "sources": sources}


def read_section(document: DocumentName, number: int) -> dict[str, Any]:
    """One section of the policy wording or the claims manual in full, with its
    document's title and version."""
    read = DOCUMENTS[document]
    if number not in read.sections:
        raise Refused(f"Section {number} of the {TITLES[document].lower()} not found")
    section = read.sections[number]
    return {
        "document": document,
        "document_title": TITLES[document],
        "version": read.version,
        "number": number,
        "title": section.title,
        "text": section.text,
        "sources": [read.source],
    }
