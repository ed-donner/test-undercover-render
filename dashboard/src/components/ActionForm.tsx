import type { ReactNode, SyntheticEvent } from "react";
import { useAction } from "../useAction";
import { FormError } from "./FormError";

// A form that asks the backend to do one thing, such as signing off a payout
// or starting a dispatch, and shows the backend's reason if it refuses. The
// button stays focusable while the request is sent, so a keyboard user can
// try again after a refusal. An icon, when given, goes before the label.
export function ActionForm({
  label,
  icon,
  ready = true,
  action,
  children,
}: Readonly<{
  label: string;
  icon?: ReactNode;
  ready?: boolean;
  action: () => Promise<unknown>;
  children?: ReactNode;
}>) {
  const { run, sending, error } = useAction(action);
  const disabled = !ready || sending;

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!disabled) run();
  }

  return (
    <form className="action-form" onSubmit={submit}>
      {children}
      <button type="submit" aria-disabled={disabled}>
        {icon}
        {label}
      </button>
      {error && <FormError>{error}</FormError>}
    </form>
  );
}
