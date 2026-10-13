import {
  Bot,
  CircleCheck,
  Flag,
  Inbox,
  type LucideIcon,
  Signature,
  Undo2,
} from "lucide-react";
import { api, type Status, statuses } from "../api";
import { DecisionChip, StatusChip } from "../components/Chips";
import { ClaimLink } from "../components/ClaimLink";
import { StateMessage } from "../components/StateMessage";
import { DispatchPanel } from "../components/DispatchPanel";
import { PageHeader } from "../components/PageHeader";
import { date, label, money, statusLabels } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";

// Each state's icon on its tile.
const STATUS_ICONS: Record<Status, LucideIcon> = {
  waiting: Inbox,
  in_progress: Bot,
  waiting_for_sign_off: Signature,
  sent_back: Undo2,
  decided: CircleCheck,
  left_for_handler: Flag,
};

export function QueuePage() {
  const { data: claims, error } = useLoad(api.listClaims, REFRESH_MS);
  const header = <PageHeader title="Claims queue" />;
  if (!claims)
    return (
      <>
        {header}
        <StateMessage error={error} />
      </>
    );

  return (
    <>
      {header}
      <section className="tiles" aria-label="Claims by state">
        {statuses.map((status) => {
          const count = claims.filter((c) => c.status === status).length;
          const Icon = STATUS_ICONS[status];
          return (
            <div
              className={`tile status-${status}`}
              key={status}
              role="group"
              aria-label={`${statusLabels[status]}: ${String(count)}`}
            >
              <p className="tile-label">{statusLabels[status]}</p>
              <p className="tile-figure">
                <span className="tile-count">{count}</span>
                <Icon />
              </p>
            </div>
          );
        })}
      </section>
      <DispatchPanel />
      <section className="panel" aria-labelledby="claims-title">
        <h2 id="claims-title">Claims</h2>
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Claim</th>
                <th>Customer</th>
                <th>Type</th>
                <th>Summary</th>
                <th className="num">Claimed</th>
                <th>Submitted</th>
                <th>State</th>
                <th>Decision</th>
                <th className="num">Payout</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((claim) => (
                <tr key={claim.claim_id}>
                  <td className="nowrap">
                    <ClaimLink claimId={claim.claim_id} />
                  </td>
                  <td className="nowrap">{claim.customer_name}</td>
                  <td className="nowrap">{label(claim.claim_type)}</td>
                  <td>{claim.summary}</td>
                  <td className="num mono">{money(claim.amount_claimed)}</td>
                  <td className="nowrap">{date(claim.submitted_on)}</td>
                  <td>
                    <StatusChip status={claim.status} />
                  </td>
                  <td>
                    {claim.decision && (
                      <DecisionChip decision={claim.decision} />
                    )}
                  </td>
                  <td className="num mono">
                    {claim.payout !== null && money(claim.payout)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
