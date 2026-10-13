import type { Calculation, Claim, Decision, Payment } from "../api";
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
          {decision.calculation && (
            <CalculationTable calculation={decision.calculation} />
          )}
          <p className="section-ref">{decision.section}</p>
          <p className="reason">{decision.reason}</p>
          <p className="small muted">
            Decided by {decision.decided_by} at {time(decision.decided_at)}
          </p>
          <p className="small muted">
            Claims manual version {decision.manual_version}
          </p>
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
          decision={decision}
          onSignedOff={onSignedOff}
        />
      )}
    </section>
  );
}

// How an approval's payout was worked out, line by line.
function CalculationTable({
  calculation,
}: Readonly<{ calculation: Calculation }>) {
  return (
    <div className="table-scroll calculation">
      <table className="table">
        <caption className="small muted">How the payout was worked out</caption>
        <tbody>
          {calculation.lines.map((line, index) => (
            // Two lines can read alike, so each is known by its place too.
            <tr key={`${String(index)} ${line.step}`}>
              <td>{line.step}</td>
              <td className="num mono">{money(line.amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Payout</th>
            <td className="num mono">{money(calculation.payout)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
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
// handler's sign-off, unless the claim is an evaluation's copy, which nobody
// can sign off.
function HeldPayment({
  claim,
  decision,
  onSignedOff,
}: Readonly<{ claim: Claim; decision: Decision; onSignedOff: () => void }>) {
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
        <SignOffForm claimId={claim.claim_id} onSignedOff={onSignedOff} />
      ) : (
        <NotAllowed action="sign this off" />
      )}
    </div>
  );
}
