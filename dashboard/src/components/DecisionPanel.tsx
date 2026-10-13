import type { Claim, Decision, Payment } from "../api";
import { money, time } from "../format";
import { useHandler } from "../handler";
import { DecisionDetails } from "./DecisionDetails";
import { NotAllowed } from "./NotAllowed";
import { SendBackForm } from "./SendBackForm";
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
  if (claim.status === "sent_back")
    return "Sent back to the agent, which hasn't taken it up yet. The next dispatch works on it.";
  if (claim.status === "left_for_handler")
    return `The agent couldn't finish this claim in ${String(claim.attempts)} attempts, so it's left for a handler.`;
  if (claim.attempts > 0) return "Back in the queue after a failed attempt.";
  return "The agent hasn't started on this claim.";
}

export function DecisionPanel({
  claim,
  onAnswered,
}: Readonly<{ claim: Claim; onAnswered: () => void }>) {
  const { decision, payment } = claim;
  const paidSignedOff = payment && whoAndWhen(payment);

  return (
    <section className="panel" aria-labelledby="decision-title">
      <h2 id="decision-title">Decision</h2>
      {!decision && <p className="muted">{progress(claim)}</p>}
      {decision && <DecisionDetails decision={decision} />}
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
          decision={decision}
          onAnswered={onAnswered}
        />
      )}
    </section>
  );
}

// Why a payment waits for a handler's sign-off: it's over the approval limit,
// or the Gateway refused it.
function WhyHeld({ decision }: Readonly<{ decision: Decision }>) {
  const amount = <span className="mono">{money(decision.payout)}</span>;
  if (decision.gateway_refusal)
    return (
      <>
        <p>
          The Gateway refused the payment of {amount}, so it waits for a
          handler's sign-off.
        </p>
        <p className="small muted">{decision.gateway_refusal}</p>
      </>
    );
  return (
    <p>
      The payment of {amount} is over the approval limit and waits for a
      handler's sign-off.
    </p>
  );
}

// A payment over the limit or refused by the Gateway, which waits for a
// handler to sign it off or send it back, unless the claim is an evaluation's
// copy, which nobody can answer.
function HeldPayment({
  claim,
  decision,
  onAnswered,
}: Readonly<{ claim: Claim; decision: Decision; onAnswered: () => void }>) {
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
      <WhyHeld decision={decision} />
      {handler.can_approve_over_limit ? (
        <div className="held-answers">
          <SignOffForm claimId={claim.claim_id} onSignedOff={onAnswered} />
          <SendBackForm claimId={claim.claim_id} onSentBack={onAnswered} />
        </div>
      ) : (
        <NotAllowed action="sign this off or send it back" />
      )}
    </div>
  );
}
