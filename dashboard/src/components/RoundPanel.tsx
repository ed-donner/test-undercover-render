import { Link } from "react-router";
import type { RoundView } from "../api";
import {
  dateTime,
  evaluationSetName,
  inWords,
  modelCost,
  money,
  percent,
  verdictLabels,
} from "../format";
import { evaluationPage } from "../paths";
import { RoundChip, RunChip, VerdictChip } from "./Chips";
import { RoundProgress } from "./RoundProgress";
import { RecipeLink, VersionLink } from "./VersionLink";

// The open or newest round: its status, where it has got to or how it ended,
// who started it, its recipe, the version it tried, its cost against its limit,
// and its evaluations.
export function RoundPanel({ round }: Readonly<{ round: RoundView }>) {
  return (
    <section className="panel" aria-labelledby="round-title">
      <div className="title-row">
        <h2 id="round-title">Round {round.number}</h2>
        <RoundChip status={round.status} />
        {round.verdict && <VerdictChip verdict={round.verdict} />}
      </div>
      {round.status === "open" ? (
        <RoundProgress round={round} />
      ) : (
        <p className="round-outcome">{outcome(round)}</p>
      )}
      <dl className="facts">
        <div>
          <dt>Started</dt>
          <dd>
            {round.started_by}, {dateTime(round.started_at)}
          </dd>
        </div>
        <div>
          <dt>Recipe</dt>
          <dd>
            <RecipeLink number={round.recipe} />
          </dd>
        </div>
        <div>
          <dt>Version tried</dt>
          {round.version === null ? (
            <dd className="muted">None yet</dd>
          ) : (
            <dd>
              <VersionLink number={round.version} />
            </dd>
          )}
        </div>
        <div>
          <dt>Cost</dt>
          <dd className="mono">
            {modelCost(round.cost)} of {money(round.spending_limit)}
          </dd>
        </div>
      </dl>
      <RoundEvaluations round={round} />
    </section>
  );
}

// How a finished or stopped round ended. A stop says who or what stopped it,
// such as "Stopped by Dana Whitfield".
function outcome(round: RoundView): string {
  if (round.status === "stopped") return round.stopped_because ?? "";
  if (!round.verdict) return "Finished. The improver proposed no change.";
  const verdict = verdictLabels[round.verdict].toLowerCase();
  return `Finished. Version ${String(round.version)} was ${verdict}: ${inWords(round.verdict_reason)}.`;
}

function RoundEvaluations({ round }: Readonly<{ round: RoundView }>) {
  if (round.evaluations.length === 0) return null;
  return (
    <div className="table-scroll">
      <table className="table">
        <caption className="small muted">The round's evaluations</caption>
        <thead>
          <tr>
            <th>Run</th>
            <th>Version</th>
            <th>Set</th>
            <th>Status</th>
            <th className="num">Accuracy</th>
          </tr>
        </thead>
        <tbody>
          {round.evaluations.map((evaluation) => (
            <tr key={evaluation.run_id}>
              <td className="mono">
                <Link to={evaluationPage(evaluation.run_id)}>
                  {evaluation.number}
                </Link>
              </td>
              <td className="mono">{evaluation.version}</td>
              <td>
                {evaluationSetName(evaluation.evaluation_set, evaluation.size)}
              </td>
              <td>
                <RunChip status={evaluation.status} />
              </td>
              <td className="num">{percent(evaluation.measures.accuracy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
