import type { Step } from "../api";

// The sections of the policy wording and the claims manual the agent read,
// once each, in a panel of their own that grows without moving the others.
export function SectionsRead({ steps }: Readonly<{ steps?: Step[] }>) {
  const read = [
    ...new Set(
      (steps ?? []).filter((s) => s.kind === "reading").map((s) => s.content),
    ),
  ];
  if (read.length === 0) return null;
  return (
    <section className="panel" aria-labelledby="sections-read-title">
      <h2 id="sections-read-title">Sections read</h2>
      <ul className="sections-read">
        {read.map((section) => (
          <li key={section}>{section}</li>
        ))}
      </ul>
    </section>
  );
}
