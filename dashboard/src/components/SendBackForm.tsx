import { Undo2 } from "lucide-react";
import { useId, useState } from "react";
import { api, NOTE_LENGTH } from "../api";
import { useAction } from "../useAction";
import { FormError } from "./FormError";
import { ReasonForm } from "./ReasonForm";

// Sends a held decision back to the agent with a note, as the handler signed
// in: a button that opens the note, which the handler must write.
export function SendBackForm({
  claimId,
  onSentBack,
}: Readonly<{ claimId: string; onSentBack: () => void }>) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const formId = useId();
  const { run, sending, error } = useAction(() =>
    api.sendBack(claimId, note.trim()).then(onSentBack),
  );

  return (
    <>
      <button
        type="button"
        className="button quiet"
        aria-expanded={open}
        aria-controls={formId}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <Undo2 />
        Send back
      </button>
      {open && (
        <ReasonForm
          id={formId}
          label="What should the agent look at again?"
          hint={`The agent reads your note as a senior handler's review and decides again. Up to ${NOTE_LENGTH.toLocaleString("en-US")} characters.`}
          submitLabel={
            <>
              <Undo2 />
              Send back to the agent
            </>
          }
          value={note}
          onChange={setNote}
          sending={sending}
          onSubmit={run}
          maxLength={NOTE_LENGTH}
        >
          {error && <FormError>{error}</FormError>}
        </ReasonForm>
      )}
    </>
  );
}
