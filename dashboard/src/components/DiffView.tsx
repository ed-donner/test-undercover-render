import { Fragment } from "react";
import type { Diff, DiffLine } from "../api";
import { LineCounts } from "./LineCounts";

// The lines that differ between two versions of a text: removed lines and added
// lines marked in color and with a sign, a gap between the hunks, and how many
// lines were added and removed.
export function DiffView({ diff }: Readonly<{ diff: Diff }>) {
  return (
    <div className="diff">
      <p className="diff-counts">
        <LineCounts added={diff.added} removed={diff.removed} /> lines
      </p>
      {diff.hunks.length === 0 ? (
        <p className="muted">No lines changed.</p>
      ) : (
        <div className="diff-lines">
          {diff.hunks.map((hunk, index) => (
            <Fragment key={index}>
              {index > 0 && <div className="diff-gap" />}
              {hunk.map((line, number) => (
                <Line key={number} line={line} />
              ))}
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}

function Line({ line }: Readonly<{ line: DiffLine }>) {
  if (line.kind === "added")
    return (
      <div className="diff-line diff-added">
        <span className="diff-sign">+</span>
        <ins>{line.text}</ins>
      </div>
    );
  if (line.kind === "removed")
    return (
      <div className="diff-line diff-removed">
        <span className="diff-sign">−</span>
        <del>{line.text}</del>
      </div>
    );
  return (
    <div className="diff-line">
      <span className="diff-sign" />
      <span>{line.text}</span>
    </div>
  );
}
