import { useCallback } from "react";
import { Link, useParams } from "react-router";
import { api, type Claim } from "../api";
import { StatusChip } from "../components/Chips";
import { DecisionPanel } from "../components/DecisionPanel";
import { StateMessage } from "../components/StateMessage";
import { PageHeader } from "../components/PageHeader";
import { HistoryPanel, PolicyPanel } from "../components/PolicyPanels";
import { SectionsRead } from "../components/SectionsRead";
import { StepList } from "../components/StepList";
import { date, label, money } from "../format";
import { evaluationPage, QUEUE } from "../paths";
import { REFRESH_MS, useLoad } from "../useLoad";

export function ClaimPage() {
  const { claimId = "" } = useParams();
  const load = useCallback(() => api.getClaim(claimId), [claimId]);
  const { data: claim, error, reload } = useLoad(load, REFRESH_MS);
  const loadSteps = useCallback(() => api.listSteps(claimId), [claimId]);
  const steps = useLoad(loadSteps, REFRESH_MS);

  if (!claim)
    return (
      <>
        <PageHeader eyebrow={<Link to={QUEUE}>Queue</Link>} title={claimId} />
        <StateMessage
          error={error}
          notFound="Claim not found. Choose one from the queue."
        />
      </>
    );

  return (
    <>
      <PageHeader
        eyebrow={
          <>
            {claim.evaluation_id ? (
              <Link to={evaluationPage(claim.evaluation_id)}>Evaluation</Link>
            ) : (
              <Link to={QUEUE}>Queue</Link>
            )}{" "}
            <span className="mono">/ {claim.claim_id}</span>
          </>
        }
        title={claim.summary}
        status={<StatusChip status={claim.status} />}
        lead={
          claim.evaluation_id ? (
            <>
              A copy of <span className="mono">{claim.copy_of}</span> in an{" "}
              <Link to={evaluationPage(claim.evaluation_id)}>evaluation</Link>
            </>
          ) : (
            `${claim.customer_name}'s ${label(claim.claim_type).toLowerCase()} claim`
          )
        }
      />
      {/* The agent's steps grow at the end of the right column, and the sections
          it read at the end of the left, so neither moves anything as the
          page refreshes. */}
      <div className="claim-layout">
        <div className="column">
          <ClaimDetails claim={claim} />
          <ItemsPanel claim={claim} />
          <DocumentsPanel claim={claim} />
          <PolicyPanel policyId={claim.policy_id} />
          <HistoryPanel customerId={claim.customer_id} />
          <SectionsRead steps={steps.data} />
        </div>
        <div className="column">
          <DecisionPanel claim={claim} onSignedOff={reload} />
          <StepList steps={steps.data} error={steps.error} />
        </div>
      </div>
    </>
  );
}

function ClaimDetails({ claim }: Readonly<{ claim: Claim }>) {
  return (
    <section className="panel" aria-labelledby="claim-title">
      <h2 id="claim-title">Claim</h2>
      <dl className="facts">
        <div>
          <dt>Customer</dt>
          <dd>{claim.customer_name}</dd>
        </div>
        <div>
          <dt>Type</dt>
          <dd>{label(claim.claim_type)}</dd>
        </div>
        <div>
          <dt>Incident</dt>
          <dd>
            {date(claim.incident_date)}, {claim.incident_location}
          </dd>
        </div>
        <div>
          <dt>Submitted</dt>
          <dd>{date(claim.submitted_on)}</dd>
        </div>
        <div>
          <dt>Amount claimed</dt>
          <dd className="mono">{money(claim.amount_claimed)}</dd>
        </div>
      </dl>
      <h3>The customer's story</h3>
      <p className="story">{claim.story}</p>
    </section>
  );
}

function ItemsPanel({ claim }: Readonly<{ claim: Claim }>) {
  const total = claim.items.reduce((sum, item) => sum + item.amount, 0);
  return (
    <section className="panel" aria-labelledby="items-title">
      <h2 id="items-title">Items claimed</h2>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Item</th>
              <th>Category</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {claim.items.map((item) => (
              <tr key={item.description}>
                <td>{item.description}</td>
                <td>{label(item.category)}</td>
                <td className="num mono">{money(item.amount)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={2}>
                Total
              </th>
              <td className="num mono">{money(total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function DocumentsPanel({ claim }: Readonly<{ claim: Claim }>) {
  return (
    <section className="panel" aria-labelledby="documents-title">
      <h2 id="documents-title">Documents</h2>
      {claim.documents.map((document) => (
        <article className="document" key={document.name}>
          <h3>{document.name}</h3>
          <p className="muted small">{label(document.type)}</p>
          <p>{document.content}</p>
        </article>
      ))}
    </section>
  );
}
