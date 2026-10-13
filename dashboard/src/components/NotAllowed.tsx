import { api } from "../api";
import { money } from "../format";
import { useHandler } from "../handler";
import { useLoad } from "../useLoad";

// Says what the signed-in handler can't do and why, in place of the button
// that would do it.
export function NotAllowed({ action }: Readonly<{ action: string }>) {
  const handler = useHandler();
  const { data: settings } = useLoad(api.getSettings);
  return (
    <p className="not-allowed">
      {settings && (
        <>
          Only a handler who can sign off payouts over{" "}
          <span className="mono">{money(settings.current.approval_limit)}</span>{" "}
          can {action}. {handler.name} can't.
        </>
      )}
    </p>
  );
}
