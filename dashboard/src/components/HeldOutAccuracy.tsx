import type { VersionScores } from "../api";
import { grade, percent } from "../format";
import { NOT_GRADED } from "../measures";

const NOT_SCORED = "Not scored yet";

// A version's accuracy on the held-out set, once rounds have scored it.
export function HeldOutAccuracy({
  scores,
}: Readonly<{ scores: VersionScores }>) {
  return scores.held_out ? (
    <span className="mono">{percent(scores.held_out.accuracy)}</span>
  ) : (
    <span className="muted">{NOT_SCORED}</span>
  );
}

// A version's grade from the judge on the held-out set, once rounds have
// scored it.
export function HeldOutGrade({ scores }: Readonly<{ scores: VersionScores }>) {
  if (!scores.held_out) return <span className="muted">{NOT_SCORED}</span>;
  const { grade: score } = scores.held_out;
  return score === null ? (
    <span className="muted">{NOT_GRADED}</span>
  ) : (
    <span className="mono">{grade(score)}</span>
  );
}
