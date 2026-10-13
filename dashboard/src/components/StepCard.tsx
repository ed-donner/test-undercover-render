import { Check, ChevronDown, LoaderCircle } from "lucide-react";
import { useId, useState } from "react";
import { CARD_KINDS } from "../copilot";
import type { CopilotStep } from "../conversation";
import { briefly, sourceOf } from "../format";

const ENDED = { refused: "Refused", failed: "Failed" } as const;

// What came back, or was asked, as a person reads it: JSON laid out, and any
// other text as it is.
function readable(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

// Where a step stands: working with the seconds so far, done with the time it
// took, or refused or failed.
function CardState({ step }: Readonly<{ step: CopilotStep }>) {
  if (step.status === "working")
    return (
      <span className="card-state">
        <LoaderCircle className="spin" aria-label="Working" />
        <span className="mono">{briefly(step.seconds)}</span>
      </span>
    );
  if (step.status === "done")
    return (
      <span className="card-state">
        <Check className="card-done" aria-label="Done" />
        <span className="mono">{briefly(step.seconds)}</span>
      </span>
    );
  return (
    <span className={`chip step-${step.status}`}>{ENDED[step.status]}</span>
  );
}

// A card for one step the Copilot took: its kind, the tool's own name and its
// main input, and where it stands, opening to what was asked and what came
// back, with the files a context layer answer came from.
export function StepCard({ step }: Readonly<{ step: CopilotStep }>) {
  const [open, setOpen] = useState(false);
  const details = useId();
  const { icon: Icon, label } = CARD_KINDS[step.kind];
  return (
    <li className={`card card-${step.kind}`}>
      <button
        type="button"
        className="card-head"
        aria-expanded={open}
        aria-controls={open ? details : undefined}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <span className="card-kind" title={label}>
          <Icon aria-label={label} />
        </span>
        <span className="card-call mono">
          <span className="card-tool">{step.tool}</span>
          {step.input && <span className="card-input"> {step.input}</span>}
        </span>
        <CardState step={step} />
        <ChevronDown className="card-open" aria-hidden />
      </button>
      {step.reason && <p className="card-reason">{step.reason}</p>}
      {open && (
        <div className="card-details" id={details}>
          <h4>Asked</h4>
          <pre>{readable(step.asked)}</pre>
          {step.answer && (
            <>
              <h4>Came back</h4>
              <pre>{readable(step.answer)}</pre>
            </>
          )}
          {step.sources.length > 0 && (
            <>
              <h4>From</h4>
              <ul className="card-sources">
                {step.sources.map((source) => (
                  <li key={source.file}>
                    <span className="mono">{source.file}</span>
                    <span className="muted"> {sourceOf(source)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </li>
  );
}
