import { Check, X } from "lucide-react";
import { useId, useState } from "react";
import {
  api,
  type ProposalKind,
  REQUEST_FAILED,
  type RoundStage,
  type RoundView,
  type WaitingProposal,
} from "../api";
import { stageLabels } from "../format";
import { useHandler } from "../handler";
import { useAction } from "../useAction";
import { ConfirmDialog } from "./ConfirmDialog";
import { DiffView } from "./DiffView";
import { ModelName } from "./ModelName";
import { NotAllowed } from "./NotAllowed";

// The stage a round is at while each kind of proposal waits.
const WAITING: Record<ProposalKind, RoundStage> = {
  change: "change_waiting",
  recipe: "recipe_waiting",
};

// The proposal waiting for a handler: what it changes and why, with Approve,
// which asks for confirmation, and Reject, which asks for a reason. Both name
// the proposal shown, so a review never lands on another; a new proposal
// starts afresh, closing the dialog and clearing the reason.
export function ProposalPanel({
  round,
  proposal,
  onReviewed,
  onRefused,
}: Readonly<{
  round: RoundView;
  proposal: WaitingProposal;
  onReviewed: () => void;
  onRefused: (refusal: string) => void;
}>) {
  const handler = useHandler();
  return (
    <section className="panel" aria-labelledby="proposal-title">
      <h2 id="proposal-title">{stageLabels[WAITING[proposal.kind]]}</h2>
      <p className="reason">{proposal.reason}</p>
      {proposal.kind === "change" && <ModelChange proposal={proposal} />}
      <DiffView diff={proposal.diff} />
      {handler.can_approve_over_limit ? (
        <Review
          key={proposal.proposal_id}
          round={round}
          proposal={proposal}
          onReviewed={onReviewed}
          onRefused={onRefused}
        />
      ) : (
        <NotAllowed action="approve or reject the improver's proposals" />
      )}
    </section>
  );
}

function ModelChange({ proposal }: Readonly<{ proposal: WaitingProposal }>) {
  const {
    model_before,
    reasoning_effort_before,
    model_after,
    reasoning_effort_after,
  } = proposal;
  if (
    !model_before ||
    !reasoning_effort_before ||
    !model_after ||
    !reasoning_effort_after
  )
    return null;
  return (
    <dl className="facts model-change">
      <div>
        <dt>Model before</dt>
        <dd>
          <ModelName
            model={model_before}
            reasoningEffort={reasoning_effort_before}
          />
        </dd>
      </div>
      <div>
        <dt>Model after</dt>
        <dd>
          <ModelName
            model={model_after}
            reasoningEffort={reasoning_effort_after}
          />
        </dd>
      </div>
    </dl>
  );
}

function Review({
  round,
  proposal,
  onReviewed,
  onRefused,
}: Readonly<{
  round: RoundView;
  proposal: WaitingProposal;
  onReviewed: () => void;
  onRefused: (refusal: string) => void;
}>) {
  const [confirming, setConfirming] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const reasonId = useId();
  const rejectId = useId();
  const ids = [round.round_id, proposal.proposal_id] as const;
  const refused = (error: unknown) => {
    onRefused(error instanceof Error ? error.message : REQUEST_FAILED);
  };
  const approve = useAction(() =>
    api.approveProposal(...ids).then(onReviewed, refused),
  );
  const reject = useAction(() =>
    api.rejectProposal(...ids, reason.trim()).then(onReviewed, refused),
  );
  const sending = approve.sending || reject.sending;
  const ready = reason.trim() !== "";
  const what = proposal.kind;

  return (
    <div className="review">
      <div className="review-buttons">
        <button
          type="button"
          className="button"
          aria-disabled={sending}
          onClick={() => {
            if (!sending) setConfirming(true);
          }}
        >
          <Check />
          Approve
        </button>
        <button
          type="button"
          className="button quiet"
          aria-expanded={rejecting}
          aria-controls={rejectId}
          onClick={() => {
            setRejecting(!rejecting);
          }}
        >
          <X />
          Reject
        </button>
      </div>
      {rejecting && (
        <form
          id={rejectId}
          className="reject-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!sending && ready) reject.run();
          }}
        >
          <label htmlFor={reasonId}>Why reject it?</label>
          <textarea
            id={reasonId}
            required
            rows={3}
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
          <p className="muted small">
            The improver reads your reason and may propose again.
          </p>
          <button
            type="submit"
            className="button"
            aria-disabled={sending || !ready}
          >
            Reject the {what}
          </button>
        </form>
      )}
      <ConfirmDialog
        open={confirming}
        title={`Approve the ${what}?`}
        confirmLabel={`Approve the ${what}`}
        onConfirm={() => {
          setConfirming(false);
          approve.run();
        }}
        onCancel={() => {
          setConfirming(false);
        }}
      >
        <p>
          {proposal.kind === "change"
            ? "The change becomes a version under test, and the improver has it evaluated. It becomes the current version only if the business's rule keeps it."
            : "The new recipe becomes the current recipe, which the next round follows."}
        </p>
      </ConfirmDialog>
    </div>
  );
}
