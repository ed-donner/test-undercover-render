import type { Claim, Payment } from "../api";
import { money, time } from "../format";
import { useHandler } from "../handler";
import { DecisionChip } from "./Chips";
import { NotAllowed } from "./NotAllowed";
import { SignOffForm } from "./SignOffForm";

type SignOff = Pick<Payment, "signed_off_by" | "signed_off_at">;

function whoAndWhen({ signed_off_by, signed_off_at }: SignOff): string | null {
  return signed_off_by && signed_off_at
    ? `${signed_off_by} at ${time(signed_off_at)}`
    : null;
}

function progress(claim: Claim): string {
  if (claim.status === "in_progress")
    return "The agent is working on this claim.";
  if (claim.status === "left_for_handler")
    return `The agent couldn't finish this claim in ${String(claim.attempts)} attempts, so it's left for a handler.`;
  if (claim.attempts > 0) return "Back in the queue after a failed attempt.";
  return "The agent hasn't started on this claim.";
}

export function DecisionPanel({
  claim,
  onSignedOff,
}: Readonly<{ claim: Claim; onSignedOff: () => void }>) {
  const { decision, payment } = claim;
  const paidSignedOff = payment && whoAndWhen(payment);

  return (
    <section className="panel" aria-labelledby="decision-title">
      <h2 id="decision-title">Decision</h2>
      {!decision && <p className="muted">{progress(claim)}</p>}
      {decision && (
        <>
          <div className="decision-line">
            <DecisionChip decision={decision.decision} />
            {decision.decision === "approve" && (
              <span className="payout mono">{money(decision.payout)}</span>
            )}
          </div>
          <p className="section-ref">{decision.section}</p>
          <p className="reason">{decision.reason}</p>
          <p className="small muted">Decided at {time(decision.decided_at)}</p>
        </>
      )}
      {payment && (
        <p className="payment">
          Paid <span className="mono">{money(payment.amount)}</span>
          {paidSignedOff && `, signed off by ${paidSignedOff}`}
        </p>
      )}
      {decision?.decision === "approve" &&
        !payment &&
        claim.status === "in_progress" && (
          <p className="payment">Waiting for the agent to pay it.</p>
        )}
      {decision && claim.status === "waiting_for_sign_off" && (
        <HeldPayment
          claim={claim}
          payout={decision.payout}
          onSignedOff={onSignedOff}
        />
      )}
    </section>
  );
}

// A payment over the limit, which waits for a handler's sign-off, unless the
// claim is an evaluation's copy, which nobody can sign off.
function HeldPayment({
  claim,
  payout,
  onSignedOff,
}: Readonly<{ claim: Claim; payout: number; onSignedOff: () => void }>) {
  const handler = useHandler();
  if (claim.evaluation_id)
    return (
      <p className="payment">
        Held for sign-off. In an evaluation this counts as finished, and a copy
        can't be signed off.
      </p>
    );
  return (
    <div className="sign-off">
      <p>
        The payment of <span className="mono">{money(payout)}</span> is over the
        approval limit and waits for a handler's sign-off.
      </p>
      {handler.can_approve_over_limit ? (
        <SignOffForm claimId={claim.claim_id} onSignedOff={onSignedOff} />
      ) : (
        <NotAllowed action="sign this off" />
      )}
    </div>
  );
}
