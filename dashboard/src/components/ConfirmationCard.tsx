import {
  Ban,
  CircleCheck,
  CircleHelp,
  CircleX,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import type { ReactNode } from "react";
import { type Outcome, outcomeOf } from "../copilot";
import type {
  Confirmation,
  ConfirmationAnswer,
  CopilotTurn,
} from "../conversation";
import { money } from "../format";
import { ClaimLink } from "./ClaimLink";
import { FormError } from "./FormError";

const ICONS: Record<Outcome["tone"], ReactNode> = {
  pending: <LoaderCircle className="spin" aria-hidden />,
  paid: <CircleCheck aria-hidden />,
  canceled: <Ban aria-hidden />,
  refused: <CircleX aria-hidden />,
  unknown: <CircleHelp aria-hidden />,
};

// The card a sign-off waits on: the claim, the customer, the amount it will pay
// and the agent's reason, all from our records, with Sign off and pay and
// Cancel, which answer this turn's card and no other. Once answered, it shows
// how the sign-off went.
export function ConfirmationCard({
  turn,
  confirmation,
  onAnswer,
  answering,
  error,
}: Readonly<{
  turn: CopilotTurn;
  confirmation: Confirmation;
  onAnswer: (turnId: string, answer: ConfirmationAnswer) => void;
  answering: boolean;
  error?: string;
}>) {
  const waiting = turn.status === "waiting_for_confirmation";
  const outcome = waiting ? undefined : outcomeOf(turn);
  return (
    <section
      className={`confirmation${waiting ? " waiting" : ""}`}
      aria-label="Confirm the sign-off"
    >
      <p className="confirmation-title">
        <ShieldCheck aria-hidden />
        {waiting ? "Sign off this payout?" : "Sign-off"}
      </p>
      <dl className="confirmation-facts">
        <div>
          <dt>Claim</dt>
          <dd>
            <ClaimLink claimId={confirmation.claim_id} />
          </dd>
        </div>
        <div>
          <dt>Customer</dt>
          <dd>{confirmation.customer_name}</dd>
        </div>
        <div className="confirmation-amount">
          <dt>Amount</dt>
          <dd className="mono">{money(confirmation.payout)}</dd>
        </div>
      </dl>
      <blockquote className="confirmation-reason">
        {confirmation.reason}
      </blockquote>
      {waiting && (
        <div className="confirmation-buttons">
          <button
            type="button"
            className="button"
            disabled={answering}
            onClick={() => {
              onAnswer(turn.turn_id, "sign_off");
            }}
          >
            Sign off and pay
          </button>
          <button
            type="button"
            className="button quiet"
            disabled={answering}
            onClick={() => {
              onAnswer(turn.turn_id, "cancel");
            }}
          >
            Cancel
          </button>
        </div>
      )}
      {error && <FormError>{error}</FormError>}
      {outcome && (
        <p className={`confirmation-outcome ${outcome.tone}`} role="status">
          {ICONS[outcome.tone]}
          <span>
            <strong>{outcome.text}</strong>
            {outcome.reason && <span className="muted"> {outcome.reason}</span>}
          </span>
        </p>
      )}
    </section>
  );
}
