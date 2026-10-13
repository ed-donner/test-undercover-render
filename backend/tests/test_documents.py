"""The documents and the payout rules seeding loads from the context layer's
files, and the contents of both documents the claim agent's instructions end
with."""

import pytest
import yaml
from sqlalchemy import select

from backend.context_files import CONTEXT
from backend.database import DATA, documents, engine, payout_rules
from backend.documents import headings, manual_version


@pytest.mark.parametrize(
    ("document", "count", "first", "last"),
    [
        ("policy_wording", 12, "Your plan", "Definitions"),
        ("claims_manual", 14, "Purpose and scope", "Records"),
    ],
)
def test_documents_split_into_numbered_sections(document, count, first, last):
    with engine().connect() as db:
        found = headings(db, document)
    assert [number for number, _ in found] == list(range(1, count + 1))
    assert (found[0][1], found[-1][1]) == (first, last)


def test_both_documents_are_seeded_from_the_context_layer_with_their_versions():
    with engine().connect() as db:
        query = select(documents).order_by(documents.c.position)
        rows = db.execute(query).mappings().all()
        version = manual_version(db)
    assert [(row["name"], row["title"], row["version"]) for row in rows] == [
        ("policy_wording", "Policy wording", "2026.1"),
        ("claims_manual", "Claims manual", "2026.2"),
    ]
    assert version == "2026.2"
    for row in rows:
        context = (CONTEXT / f"{row['name']}.md").read_text(encoding="utf-8")
        # The labs' copy in data/ is the same document without its front matter.
        labs = (DATA / f"{row['name']}.md").read_text(encoding="utf-8")
        assert row["text"] == labs
        assert context.startswith("---\nsource:\n")
        assert context.endswith(f"---\n\n{labs}")


def test_the_payout_rules_are_the_context_layers_plans():
    plans = yaml.safe_load((CONTEXT / "plans.yaml").read_text(encoding="utf-8"))
    del plans["source"]
    with engine().connect() as db:
        assert db.execute(select(payout_rules.c.plans)).scalar_one() == plans


def test_the_claim_agent_reads_the_contents_of_both_documents(client):
    claim = client.get("/api/versions/current").json()["instructions"]
    assert claim.startswith("# UnderCover Agent: working a claim")
    contents = claim[claim.index("## Contents of the policy wording") :]
    assert "\n3. Trip Delay\n" in contents
    assert "## Contents of the claims manual" in contents
    assert contents.endswith("14. Records\n")
    assert "Unattended means out of your sight" not in claim
    assert "Monkeys, gulls, bears, giraffes" not in claim
