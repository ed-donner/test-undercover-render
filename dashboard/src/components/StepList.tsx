import { Shield } from "lucide-react";
import type { Step } from "../api";
import { time } from "../format";
import { StateMessage } from "./StateMessage";

const SUMMARY_LENGTH = 90;

// The agent's steps on a claim as it works, oldest first, so a new step joins
// the end and moves nothing above it.
export function StepList({
  steps,
  error,
}: Readonly<{ steps?: Step[]; error?: Error }>) {
  return (
    <section className="panel" aria-labelledby="steps-title">
      <h2 id="steps-title">Agent at work</h2>
      {!steps && <StateMessage error={error} />}
      {steps?.length === 0 && (
        <StateMessage empty="No steps yet. They appear here as the agent works on the claim." />
      )}
      {steps && steps.length > 0 && (
        <ol className="steps">
          {steps.map((step) => (
            <li key={step.step_id} className="step">
              <span className="step-time small muted">
                {time(step.created_at)}
              </span>
              <StepBody step={step} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function StepBody({ step }: Readonly<{ step: Step }>) {
  if (step.kind === "screening")
    return (
      <p className="step-check">
        <Shield />
        <span>
          <span className="step-label">Security check</span> {step.content}
        </span>
      </p>
    );
  if (step.kind === "tool_call")
    return (
      <p>
        <span className="step-label">Called</span>{" "}
        <code className="mono">{step.content}</code>
      </p>
    );
  if (step.kind === "tool_result") {
    const summary =
      step.content.length > SUMMARY_LENGTH
        ? `${step.content.slice(0, SUMMARY_LENGTH)}...`
        : step.content;
    return (
      <details>
        <summary>
          <span className="step-label">Result</span>{" "}
          <code className="mono">{summary}</code>
        </summary>
        <pre className="step-result">{step.content}</pre>
      </details>
    );
  }
  if (step.kind === "reading")
    return (
      <p>
        <span className="step-label">Read</span> {step.content}
      </p>
    );
  if (step.kind === "error")
    return (
      <p>
        <span className="chip step-failed">Failed</span> {step.content}
      </p>
    );
  return (
    <p>
      <span className="step-label">Agent</span> {step.content}
    </p>
  );
}
