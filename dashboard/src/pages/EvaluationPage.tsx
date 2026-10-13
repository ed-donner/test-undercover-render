import { useCallback } from "react";
import { Link, useParams } from "react-router";
import { api, type ScoredClaim, type ScoredEvaluation } from "../api";
import { DecisionPayout, RightChip, RunChip } from "../components/Chips";
import { ClaimLink } from "../components/ClaimLink";
import { Check, GradeChip } from "../components/Judging";
import { StateMessage } from "../components/StateMessage";
import { ModelName } from "../components/ModelName";
import { PageHeader } from "../components/PageHeader";
import {
  agentsAtOnce,
  dateTime,
  duration,
  evaluationSetName,
  modelCost,
  money,
} from "../format";
import { MEASURES } from "../measures";
import { SCOREBOARD } from "../paths";
import { REFRESH_MS, useLoad } from "../useLoad";

export function EvaluationPage() {
  const { runId = "" } = useParams();
  const load = useCallback(() => api.getEvaluation(runId), [runId]);
  const { data: evaluation, error } = useLoad(load, REFRESH_MS);

  if (!evaluation)
    return (
      <>
        <PageHeader
          eyebrow={<Link to={SCOREBOARD}>Scoreboard</Link>}
          title="Evaluation"
        />
        <StateMessage
          error={error}
          notFound="Evaluation not found. Choose one on the Scoreboard."
        />
      </>
    );

  return (
    <>
      <PageHeader
        eyebrow={<Link to={SCOREBOARD}>Scoreboard</Link>}
        title={`Evaluation #${String(evaluation.number)}`}
        status={<RunChip status={evaluation.status} />}
      />
      <div className="column">
        <MeasuresPanel evaluation={evaluation} />
        <ScoredClaims claims={evaluation.claims} />
      </div>
    </>
  );
}

function MeasuresPanel({
  evaluation,
}: Readonly<{ evaluation: ScoredEvaluation }>) {
  return (
    <section className="panel" aria-labelledby="measures-title">
      <h2 id="measures-title">Measures</h2>
      <p className="muted small">
        {evaluationSetName(evaluation.evaluation_set, evaluation.size)}, with{" "}
        {agentsAtOnce(evaluation.agents)} on{" "}
        <ModelName
          model={evaluation.model}
          reasoningEffort={evaluation.reasoning_effort}
        />
        , version {evaluation.version}. Started{" "}
        {dateTime(evaluation.started_at)}. Model cost{" "}
        <span className="mono">{modelCost(evaluation.model_cost)}</span> and
        judge cost{" "}
        <span className="mono">{modelCost(evaluation.judge_cost)}</span>.
      </p>
      <dl className="facts measures">
        {MEASURES.map(({ label, show }) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className="mono">{show(evaluation.measures)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ScoredClaims({ claims }: Readonly<{ claims: ScoredClaim[] }>) {
  return (
    <section className="panel" aria-labelledby="claims-title">
      <h2 id="claims-title">Claims</h2>
      <p className="muted small">
        A claim the agent didn't decide counts as a referral and gets an F from
        the judge.
      </p>
      <div className="table-scroll">
        <table className="table steady scored-claims">
          <colgroup>
            <col className="col-claim" />
            <col className="col-id" />
            <col className="col-decision" />
            <col className="col-decision" />
            <col className="col-chip" />
            <col className="col-chip" />
            <col className="col-chip" />
            <col className="col-chip" />
            <col className="col-money" />
            <col className="col-money" />
            <col className="col-time" />
            <col className="col-reason" />
          </colgroup>
          <thead>
            <tr>
              <th>Copy</th>
              <th>Of</th>
              <th>Handler</th>
              <th>Agent</th>
              <th>Score</th>
              <th>Grade</th>
              <th>Same grounds</th>
              <th>Same section</th>
              <th className="num">Mistake cost</th>
              <th className="num">Model cost</th>
              <th className="num">Time</th>
              <th>The agent's reason</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim) => (
              <tr key={claim.claim_id}>
                <td className="nowrap">
                  <ClaimLink claimId={claim.claim_id} />
                </td>
                <td className="mono nowrap">{claim.copy_of}</td>
                <td className="nowrap">
                  <DecisionPayout
                    decision={claim.handler_decision}
                    payout={claim.handler_payout}
                  />
                </td>
                <td className="nowrap">
                  {claim.decision && claim.payout !== null ? (
                    <DecisionPayout
                      decision={claim.decision}
                      payout={claim.payout}
                    />
                  ) : (
                    <span className="muted">No decision</span>
                  )}
                </td>
                <td>
                  <RightChip right={claim.right} />
                </td>
                <td>
                  <GradeChip grade={claim.grade} />
                </td>
                <td>
                  {claim.grade && <Check chance={claim.grade.same_grounds} />}
                </td>
                <td>
                  {claim.grade && <Check chance={claim.grade.same_section} />}
                </td>
                <td className="num mono">{money(claim.mistake_cost)}</td>
                <td className="num mono">{modelCost(claim.model_cost)}</td>
                <td className="num mono">{duration(claim.seconds)}</td>
                <td className="small">
                  <span className="two-lines" title={claim.reason ?? undefined}>
                    {claim.reason}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
