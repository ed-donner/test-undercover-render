"""A handler's answer to an approval held for sign-off, read from the app's record of
the claim: who signed it off, or who sent it back with which note, or no answer
yet; and the message that gives the claim agent's model a note sent back."""

from typing import Any

from langchain_core.messages import HumanMessage

SIGNED_OFF = "signed_off"
SENT_BACK = "sent_back"

# The answer a paused claim graph resumes with, such as
# {"answer": "signed_off", "by": "Dana Whitfield"}, or
# {"answer": "sent_back", "by": "Dana Whitfield", "note": "..."}.
Answer = dict[str, str]

# What the model is told of a decision sent back. It's code rather than the
# claim agent's instructions, so no version of the instructions can drop it.
NOTE_MESSAGE = (
    "{by}, a senior handler, sent your decision on this claim back to you with "
    "this note:\n\n{note}\n\n"
    "Your earlier decision no longer stands, and nothing has been paid on it. "
    "Treat the note as a senior handler's review of your decision: check what it "
    "says against the policy wording and the claims manual, as you check "
    "everything else, then record a new decision. If the wording doesn't support "
    "what the note asks, refer the claim to a handler and say why."
)


def answer_of(claim: dict[str, Any]) -> Answer | None:
    """The handler's answer on the claim's record: who signed its decision off, or,
    for a claim with no decision now, who sent its newest decision back and with
    which note; or None while it waits for an answer."""
    decision, sent_back = claim["decision"], claim["sent_back_decisions"]
    if decision and decision["signed_off_by"]:
        return {"answer": SIGNED_OFF, "by": decision["signed_off_by"]}
    if decision is None and sent_back:
        newest = sent_back[-1]
        by, note = newest["sent_back_by"], newest["note"]
        return {"answer": SENT_BACK, "by": by, "note": note}
    return None


def note_message(answer: Answer) -> HumanMessage:
    """The message that gives the claim agent's model a decision sent back: who sent
    it back, the note, and how to treat it."""
    return HumanMessage(NOTE_MESSAGE.format(by=answer["by"], note=answer["note"]))
