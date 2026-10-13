import type { ClaimGrade } from "../api";
import { grade as shownGrade } from "../format";
import { NOT_GRADED } from "../measures";

// The judge's grade of a claim's explanation as a chip, with its score.
export function GradeChip({ grade }: Readonly<{ grade: ClaimGrade | null }>) {
  if (!grade) return <span className="muted">{NOT_GRADED}</span>;
  return (
    <span className="nowrap">
      <span className={`chip grade-${grade.letter}`}>{grade.letter}</span>{" "}
      <span className="mono">{shownGrade(grade.score)}</span>
    </span>
  );
}

// Whether the judge found the same grounds or the same section: yes from even
// odds.
export function Check({ chance }: Readonly<{ chance: number }>) {
  return <>{chance >= 0.5 ? "Yes" : "No"}</>;
}
