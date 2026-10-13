// A model at its reasoning effort, such as openai/gpt-6-luna at low.
export function ModelName({
  model,
  reasoningEffort,
}: Readonly<{ model: string; reasoningEffort: string }>) {
  return (
    <>
      <span className="mono nowrap">{model}</span> at {reasoningEffort}
    </>
  );
}
