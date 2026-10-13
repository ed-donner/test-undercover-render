import { ArrowUp } from "lucide-react";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { ASK, MESSAGE_LENGTH } from "../copilot";
import { FormError } from "./FormError";

// The most lines the box grows to before it scrolls, where the browser can't
// size it to its text.
const MOST_LINES = 6;

// The box a handler asks the Copilot in: Enter sends and Shift+Enter starts a
// new line. While the Copilot works or a confirmation waits it says why it
// can't take a message yet, and once it can, the handler is back in it, unless
// they've gone elsewhere. A message the app refuses stays in the box, with the
// reason.
export function MessageBox({
  onSend,
  waitingFor,
  sending,
  error,
}: Readonly<{
  onSend: (message: string) => Promise<boolean>;
  waitingFor?: string;
  sending: boolean;
  error?: string;
}>) {
  const [message, setMessage] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const sentFromHere = useRef(false);
  const disabled = waitingFor !== undefined || sending;
  const ready = !disabled && message.trim() !== "";

  useEffect(() => {
    if (disabled || !sentFromHere.current) return;
    sentFromHere.current = false;
    if (document.activeElement === document.body) box.current?.focus();
  }, [disabled]);

  function send() {
    if (!ready) return;
    sentFromHere.current = true;
    void onSend(message.trim()).then((sent) => {
      if (sent) setMessage("");
    });
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    )
      return;
    event.preventDefault();
    send();
  }

  return (
    <form
      className="message-box"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      {error && <FormError>{error}</FormError>}
      <div className="message-field">
        <textarea
          ref={box}
          aria-label={ASK}
          placeholder={waitingFor ?? ASK}
          value={message}
          disabled={disabled}
          rows={Math.min(MOST_LINES, message.split("\n").length)}
          maxLength={MESSAGE_LENGTH}
          onChange={(event) => {
            setMessage(event.target.value);
          }}
          onKeyDown={onKeyDown}
        />
        <button
          type="submit"
          className="send"
          aria-label="Send"
          disabled={!ready}
        >
          <ArrowUp aria-hidden />
        </button>
      </div>
    </form>
  );
}
