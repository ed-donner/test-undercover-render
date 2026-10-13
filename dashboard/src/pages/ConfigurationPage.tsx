import { api, type VersionSummary } from "../api";
import { VersionChip } from "../components/Chips";
import { Approval } from "../components/Approval";
import { HeldOutAccuracy, HeldOutGrade } from "../components/HeldOutAccuracy";
import { PageHeader } from "../components/PageHeader";
import { StateMessage } from "../components/StateMessage";
import { VersionChanges } from "../components/VersionChanges";
import { VersionLink } from "../components/VersionLink";
import { label } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";

export function ConfigurationPage() {
  const { data: configuration, error } = useLoad(
    api.getConfiguration,
    REFRESH_MS,
  );
  const current = configuration?.versions.find(
    (version) => version.number === configuration.current,
  );
  const header = (
    <PageHeader
      title="Configuration"
      lead="All versions of the claim agent's configuration."
    />
  );

  if (!configuration || !current)
    return (
      <>
        {header}
        <StateMessage error={error} />
      </>
    );
  return (
    <>
      {header}
      <div className="column">
        <CurrentVersion version={current} />
        <Versions versions={configuration.versions} />
      </div>
    </>
  );
}

function CurrentVersion({ version }: Readonly<{ version: VersionSummary }>) {
  return (
    <section className="panel" aria-labelledby="current-title">
      <h2 id="current-title">Current version</h2>
      <dl className="facts">
        <div>
          <dt>Version</dt>
          <dd>
            <VersionLink number={version.number} />
          </dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd className="mono nowrap">{version.model}</dd>
        </div>
        <div>
          <dt>Reasoning effort</dt>
          <dd>{label(version.reasoning_effort)}</dd>
        </div>
        <div>
          <dt>Held-out accuracy</dt>
          <dd>
            <HeldOutAccuracy scores={version.scores} />
          </dd>
        </div>
        <div>
          <dt>Held-out grade</dt>
          <dd>
            <HeldOutGrade scores={version.scores} />
          </dd>
        </div>
      </dl>
    </section>
  );
}

function Versions({ versions }: Readonly<{ versions: VersionSummary[] }>) {
  return (
    <section className="panel" aria-labelledby="versions-title">
      <h2 id="versions-title">Versions</h2>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Version</th>
              <th>Status</th>
              <th>What changed</th>
              <th>Reason</th>
              <th>Proposed by</th>
              <th>Approved</th>
              <th className="num">Held-out accuracy</th>
              <th className="num">Held-out grade</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((version) => (
              <tr key={version.number}>
                <td className="nowrap">
                  <VersionLink number={version.number} />
                </td>
                <td>
                  <VersionChip status={version.status} />
                </td>
                <td>
                  <VersionChanges version={version} />
                </td>
                <td>{version.reason}</td>
                <td>{version.proposed_by}</td>
                <td>
                  <Approval by={version.approved_by} at={version.approved_at} />
                </td>
                <td className="num">
                  <HeldOutAccuracy scores={version.scores} />
                </td>
                <td className="num">
                  <HeldOutGrade scores={version.scores} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
