import type { VersionSummary } from "../api";
import { LineCounts } from "./LineCounts";
import { ModelName } from "./ModelName";

// What a version changed from the one it was based on: lines of its
// instructions, and its model or reasoning effort.
export function VersionChanges({
  version,
}: Readonly<{ version: VersionSummary }>) {
  const { model_before, reasoning_effort_before } = version;
  if (model_before === null || reasoning_effort_before === null)
    return <>The first version</>;
  const modelChanged =
    version.model !== model_before ||
    version.reasoning_effort !== reasoning_effort_before;
  return (
    <>
      <LineCounts added={version.lines_added} removed={version.lines_removed} />{" "}
      lines
      {modelChanged && (
        <>
          ,{" "}
          <ModelName
            model={model_before}
            reasoningEffort={reasoning_effort_before}
          />{" "}
          to{" "}
          <ModelName
            model={version.model}
            reasoningEffort={version.reasoning_effort}
          />
        </>
      )}
    </>
  );
}
