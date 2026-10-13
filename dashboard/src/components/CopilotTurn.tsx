import { CircleAlert, Clock } from "lucide-react";
import { STOPPED, smallPrint } from "../copilot";
import type {
  ConfirmationAnswer,
  CopilotStep,
  CopilotTurn as Turn,
} from "../conversation";
import { ConfirmationCard } from "./ConfirmationCard";
import { Markdown } from "./Markdown";
import { StepCard } from "./StepCard";

// A small working indicator, while the Copilot works between steps. The
// sidebar tells a screen reader where the turn stands, once.
function Working() {
  return (
    <p className="working">
      <span className="working-dots" aria-hidden>
        <span />
        <span />
        <span />
      </span>
      Working
    </p>
  );
}

function Cards({ steps }: Readonly<{ steps: CopilotStep[] }>) {
  if (steps.length === 0) return null;
  return (
    <ol className="cards" aria-label="Steps">
      {steps.map((step) => (
        <StepCard key={step.step_id} step={step} />
      ))}
    </ol>
  );
}

// One turn of a conversation: the handler's message, the Copilot's cards as it
// takes each step, a confirmation card when a sign-off waits, and its answer,
// or what went wrong.
export function CopilotTurn({
  turn,
  onAnswer,
  answering,
  answerError,
}: Readonly<{
  turn: Turn;
  onAnswer: (turnId: string, answer: ConfirmationAnswer) => void;
  answering: boolean;
  answerError?: string;
}>) {
  const working = turn.status === "working";
  const stepWorking = turn.steps.some((step) => step.status === "working");
  // The cards from before a pause, then its confirmation, then the cards after.
  const pausedAt = turn.paused_at;
  const before = turn.steps.filter(
    (step) => pausedAt === null || step.started_at < pausedAt,
  );
  const after = turn.steps.filter((step) => !before.includes(step));
  return (
    <li className={working ? "turn turn-working" : "turn"}>
      <p className="from-handler">{turn.message}</p>
      <Cards steps={before} />
      {turn.confirmation && (
        <ConfirmationCard
          turn={turn}
          confirmation={turn.confirmation}
          onAnswer={onAnswer}
          answering={answering}
          error={answerError}
        />
      )}
      <Cards steps={after} />
      {working && !stepWorking && <Working />}
      {turn.answer && (
        <div className="from-copilot">
          <div className="answer">
            <Markdown text={turn.answer} />
          </div>
          <p className="small-print">{smallPrint(turn)}</p>
        </div>
      )}
      {turn.status === "failed" && (
        <p className="turn-ended failed">
          <CircleAlert aria-hidden />
          <span>
            The Copilot couldn't finish this: {turn.failure ?? "it failed"}
          </span>
        </p>
      )}
      {turn.status === "stopped" && (
        <p className="turn-ended">
          <Clock aria-hidden />
          <span>{STOPPED}</span>
        </p>
      )}
    </li>
  );
}
