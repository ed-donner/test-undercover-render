import type { RoundView } from "../api";
import { roundStages, stageLabels, whereRoundIs } from "../format";

// Where a round has got to: its stages in order, those behind it done, the one
// it's at with how far it has got, and those ahead to come. The improver may go
// back to work after a rejection, which shows as the improver working again.
export function RoundProgress({ round }: Readonly<{ round: RoundView }>) {
  const at = round.stage === null ? -1 : roundStages.indexOf(round.stage);
  return (
    <ol className="round-progress" aria-label="Where the round has got to">
      {roundStages.map((stage, index) => {
        const where = whereStageIs(index, at);
        return (
          <li
            key={stage}
            className={`stage stage-${where}`}
            aria-current={where === "current" ? "step" : undefined}
          >
            <span className="stage-mark" aria-hidden="true" />
            <span className="stage-name">
              {where === "current" ? whereRoundIs(round) : stageLabels[stage]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function whereStageIs(index: number, at: number) {
  if (index < at) return "done";
  return index === at ? "current" : "ahead";
}
