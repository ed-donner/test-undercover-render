import {
  Ban,
  BookOpen,
  History,
  NotebookPen,
  Shield,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Step } from "../api";
import { sourceOf, time } from "../format";
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

// A step with an icon that says at a glance what kind it is.
function Marked({
  icon: Icon,
  label,
  children,
}: Readonly<{ icon: LucideIcon; label: string; children: ReactNode }>) {
  return (
    <div className="step-marked">
      <Icon />
      <div>
        <span className="step-label">{label}</span> {children}
      </div>
    </div>
  );
}

function StepBody({ step }: Readonly<{ step: Step }>) {
  if (step.kind === "screening")
    return (
      <Marked icon={Shield} label="Security check">
        {step.content}
      </Marked>
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
  if (step.kind === "lookup")
    return (
      <Marked icon={BookOpen} label="Looked up">
        {step.content}
        {step.sources.length === 0 ? (
          <p className="step-sources small muted">Found nothing</p>
        ) : (
          <ul className="step-sources small muted">
            {step.sources.map((source) => (
              <li key={source.file}>
                <span className="mono">{source.file}</span>: {sourceOf(source)}
              </li>
            ))}
          </ul>
        )}
      </Marked>
    );
  if (step.kind === "memory_search")
    return (
      <Marked icon={History} label="Searched memory">
        <span className="step-text">{step.content}</span>
      </Marked>
    );
  if (step.kind === "memory_save")
    return (
      <Marked icon={NotebookPen} label="Saved to memory">
        <span className="step-text">{step.content}</span>
      </Marked>
    );
  if (step.kind === "refusal")
    return (
      <p>
        <span className="chip step-refused">
          <Ban />
          Refused
        </span>{" "}
        <code className="mono">{step.content}</code>
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
