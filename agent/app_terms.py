"""The app's words for its records, as the claim agent and the Copilot both read
them: where a claim stands, the kinds of decision and run, where a run stands, and
the labeled sets an evaluation works."""

from enum import StrEnum
from typing import Literal

DecisionKind = Literal["approve", "decline", "refer"]
APPROVE: DecisionKind = "approve"
REFER: DecisionKind = "refer"
RunKind = Literal["dispatch", "evaluation"]
DISPATCH: RunKind = "dispatch"
EVALUATION: RunKind = "evaluation"
RunStatus = Literal["running", "finished", "stopped"]
RUNNING: RunStatus = "running"
STOPPED: RunStatus = "stopped"
EvaluationSet = Literal["evaluation", "held_out"]
HELD_OUT: EvaluationSet = "held_out"


class Status(StrEnum):
    """Where a claim stands."""

    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_SIGN_OFF = "waiting_for_sign_off"
    SENT_BACK = "sent_back"
    DECIDED = "decided"
    LEFT_FOR_HANDLER = "left_for_handler"
