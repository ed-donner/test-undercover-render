import type { Calculation, DecisionRecord } from "../api";
import { money, time } from "../format";
import { DecisionChip } from "./Chips";

// A decision's whole record, as claims manual section 14 asks for it: the
// decision and its payout, how the payout was worked out, the section, the
// reason, who made it and when, and the manual's version.
export function DecisionDetails({
  decision,
}: Readonly<{ decision: DecisionRecord }>) {
  return (
    <>
      <div className="decision-line">
        <DecisionChip decision={decision.decision} />
        {decision.decision === "approve" && (
          <span className="payout mono">{money(decision.payout)}</span>
        )}
      </div>
      {decision.calculation && (
        <CalculationTable calculation={decision.calculation} />
      )}
      <p className="section-ref">{decision.section}</p>
      <p className="reason">{decision.reason}</p>
      <p className="small muted">
        Decided by {decision.decided_by} at {time(decision.decided_at)}
      </p>
      <p className="small muted">
        Claims manual version {decision.manual_version}
      </p>
    </>
  );
}

// How an approval's payout was worked out, line by line.
function CalculationTable({
  calculation,
}: Readonly<{ calculation: Calculation }>) {
  return (
    <div className="table-scroll calculation">
      <table className="table">
        <caption className="small muted">How the payout was worked out</caption>
        <tbody>
          {calculation.lines.map((line, index) => (
            // Two lines can read alike, so each is known by its place too.
            <tr key={`${String(index)} ${line.step}`}>
              <td>{line.step}</td>
              <td className="num mono">{money(line.amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Payout</th>
            <td className="num mono">{money(calculation.payout)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
