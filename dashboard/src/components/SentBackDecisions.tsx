import type { SentBackDecision } from "../api";
import { time } from "../format";
import { DecisionDetails } from "./DecisionDetails";

// The decisions senior handlers sent back to the agent, oldest first, each with
// its whole record, the note, who sent it back and when. Nothing shows for a
// claim with none.
export function SentBackDecisions({
  decisions,
}: Readonly<{ decisions: SentBackDecision[] }>) {
  if (decisions.length === 0) return null;
  return (
    <section className="panel" aria-labelledby="sent-back-title">
      <h2 id="sent-back-title">Decisions sent back</h2>
      <ol className="sent-back">
        {decisions.map((decision) => (
          <li key={decision.sent_back_at + decision.decided_at}>
            <DecisionDetails decision={decision} />
            <blockquote className="note">{decision.note}</blockquote>
            <p className="small muted">
              Sent back by {decision.sent_back_by} at{" "}
              {time(decision.sent_back_at)}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
