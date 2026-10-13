import type {
  DecisionKind,
  RoundStatus,
  RunStatus,
  Status,
  Verdict,
  VersionStatus,
} from "../api";
import {
  decisionLabels,
  money,
  roundLabels,
  runLabels,
  statusLabels,
  verdictLabels,
  versionLabels,
} from "../format";

export function StatusChip({ status }: Readonly<{ status: Status }>) {
  return (
    <span className={`chip status-${status}`}>{statusLabels[status]}</span>
  );
}

export function DecisionChip({
  decision,
}: Readonly<{ decision: DecisionKind }>) {
  return (
    <span className={`chip decision-${decision}`}>
      {decisionLabels[decision]}
    </span>
  );
}

export function RunChip({ status }: Readonly<{ status: RunStatus }>) {
  return <span className={`chip run-${status}`}>{runLabels[status]}</span>;
}

export function VersionChip({ status }: Readonly<{ status: VersionStatus }>) {
  return (
    <span className={`chip version-${status}`}>{versionLabels[status]}</span>
  );
}

export function RoundChip({ status }: Readonly<{ status: RoundStatus }>) {
  return <span className={`chip round-${status}`}>{roundLabels[status]}</span>;
}

export function VerdictChip({ verdict }: Readonly<{ verdict: Verdict }>) {
  return (
    <span className={`chip verdict-${verdict}`}>{verdictLabels[verdict]}</span>
  );
}

// Whether the agent's decision and payout match the handler's.
export function RightChip({ right }: Readonly<{ right: boolean }>) {
  return right ? (
    <span className="chip score-right">Right</span>
  ) : (
    <span className="chip score-miss">Miss</span>
  );
}

export function DecisionPayout({
  decision,
  payout,
}: Readonly<{ decision: DecisionKind; payout: number }>) {
  return (
    <>
      <DecisionChip decision={decision} />{" "}
      <span className="mono">{money(payout)}</span>
    </>
  );
}
