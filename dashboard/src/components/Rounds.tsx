import type { Measures, RoundReview, RoundSummary } from "../api";
import {
  dateTime,
  grade,
  inWords,
  modelCost,
  money,
  percent,
  whereRoundIs,
} from "../format";
import { NOT_GRADED } from "../measures";
import { RoundChip, VerdictChip } from "./Chips";
import { StateMessage } from "./StateMessage";
import { RecipeLink, VersionLink } from "./VersionLink";

const HEADINGS: [string, string][] = [
  ["Round", ""],
  ["Recipe", ""],
  ["Version tried", ""],
  ["Held-out accuracy", "num"],
  ["Held-out grade", "num"],
  ["Verdict", ""],
  ["Cost", "num"],
];

// Every round, newest first: what it tried, the held-out scores before and
// after, its verdict and why, and what it cost against its limit, with the
// improver's reason and who approved or rejected what and when on a line of
// its own beneath.
export function Rounds({ rounds }: Readonly<{ rounds: RoundSummary[] }>) {
  return (
    <section className="panel" aria-labelledby="rounds-title">
      <h2 id="rounds-title">Rounds</h2>
      {rounds.length === 0 ? (
        <StateMessage empty="No rounds yet. Starting a round has the improver read the latest results and propose a change to the claim agent for a handler to approve." />
      ) : (
        <div className="table-scroll">
          <table className="table rounds">
            <thead>
              <tr>
                {HEADINGS.map(([heading, className]) => (
                  <th key={heading} className={className || undefined}>
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            {rounds.map((round) => (
              <RoundRows key={round.round_id} round={round} />
            ))}
          </table>
        </div>
      )}
    </section>
  );
}

function RoundRows({ round }: Readonly<{ round: RoundSummary }>) {
  return (
    <tbody>
      <tr>
        <td>
          <span className="nowrap">
            <span className="mono">{round.number}</span>{" "}
            <RoundChip status={round.status} />
          </span>
          {round.status === "open" && (
            <span className="round-stage small">{whereRoundIs(round)}</span>
          )}
        </td>
        <td className="nowrap">
          <RecipeLink number={round.recipe} />
        </td>
        {round.version === null ? (
          <td className="muted">None</td>
        ) : (
          <td className="nowrap">
            <VersionLink number={round.version} />
          </td>
        )}
        <td className="num">
          <BeforeAfter
            round={round}
            show={(measures) => percent(measures.accuracy)}
          />
        </td>
        <td className="num">
          <BeforeAfter
            round={round}
            show={(measures) =>
              measures.grade === null ? NOT_GRADED : grade(measures.grade)
            }
          />
        </td>
        <td className="round-verdict">
          {round.verdict ? (
            <>
              <VerdictChip verdict={round.verdict} />{" "}
              <span className="small">{inWords(round.verdict_reason)}</span>
            </>
          ) : (
            <span className="muted">{round.stopped_because ?? "None"}</span>
          )}
        </td>
        <td className="num">
          {modelCost(round.cost)} of {money(round.spending_limit)}
        </td>
      </tr>
      {(round.reason !== null || round.reviews.length > 0) && (
        <tr>
          <td colSpan={HEADINGS.length} className="round-details small">
            <div>
              {round.reason && (
                <p>
                  <span className="muted">The improver's reason:</span>{" "}
                  {round.reason}
                </p>
              )}
              <Reviews reviews={round.reviews} />
            </div>
          </td>
        </tr>
      )}
    </tbody>
  );
}

// A held-out score before the round's version and after it, each side shown
// on its own, since a version the round couldn't afford to evaluate has no
// score after.
function BeforeAfter({
  round,
  show,
}: Readonly<{ round: RoundSummary; show: (measures: Measures) => string }>) {
  const { held_out_before: before, held_out_after: after } = round;
  if (!before && !after) return <span className="muted">None</span>;
  return (
    <>
      {before ? show(before) : "None"} to {after ? show(after) : "None"}
    </>
  );
}

function Reviews({ reviews }: Readonly<{ reviews: RoundReview[] }>) {
  if (reviews.length === 0) return null;
  return (
    <ul className="reviews">
      {reviews.map((review) => (
        <li key={review.reviewed_at}>
          <span className="nowrap">{review.reviewed_by}</span> {review.review}{" "}
          the {review.kind},{" "}
          <span className="nowrap">{dateTime(review.reviewed_at)}</span>
          {review.rejection_reason && (
            <span className="muted">: {review.rejection_reason}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
