import type { Step } from "../api";
import type { Source } from "../sources";
import { sourceOf } from "../format";

interface FileUsed {
  source: Source;
  lookedUp: Set<string>;
}

interface ContextFound {
  files: FileUsed[];
  foundNothing: Set<string>;
}

// Everything the agent looked up in the context layer, once each, grouped by
// the file it came from, and what found nothing.
function contextFound(steps: Step[]): ContextFound {
  const files = new Map<string, FileUsed>();
  const foundNothing = new Set<string>();
  for (const lookup of steps.filter((step) => step.kind === "lookup")) {
    if (lookup.sources.length === 0) foundNothing.add(lookup.content);
    for (const source of lookup.sources) {
      const used = files.get(source.file) ?? { source, lookedUp: new Set() };
      used.lookedUp.add(lookup.content);
      files.set(source.file, used);
    }
  }
  return { files: [...files.values()], foundNothing };
}

function LookedUpList({ lookedUp }: Readonly<{ lookedUp: Set<string> }>) {
  return (
    <ul>
      {[...lookedUp].map((looked) => (
        <li key={looked}>{looked}</li>
      ))}
    </ul>
  );
}

// The context the agent used, each file with its source, in a panel of its
// own that grows without moving the others.
export function ContextUsed({ steps }: Readonly<{ steps?: Step[] }>) {
  const { files, foundNothing } = contextFound(steps ?? []);
  if (files.length === 0 && foundNothing.size === 0) return null;
  return (
    <section className="panel" aria-labelledby="context-used-title">
      <h2 id="context-used-title">Context used</h2>
      <div className="context-files">
        {files.map(({ source, lookedUp }) => (
          <div className="context-file" key={source.file}>
            <h3 className="mono">{source.file}</h3>
            <p className="small muted">{sourceOf(source)}</p>
            <LookedUpList lookedUp={lookedUp} />
          </div>
        ))}
        {foundNothing.size > 0 && (
          <div className="context-file">
            <h3>Found nothing</h3>
            <LookedUpList lookedUp={foundNothing} />
          </div>
        )}
      </div>
    </section>
  );
}
