import { Signature } from "lucide-react";
import { api } from "../api";
import { ActionForm } from "./ActionForm";

// Signs off a held payout as the handler signed in.
export function SignOffForm({
  claimId,
  onSignedOff,
}: Readonly<{ claimId: string; onSignedOff: () => void }>) {
  return (
    <ActionForm
      label="Sign off"
      icon={<Signature />}
      action={() => api.signOff(claimId).then(onSignedOff)}
    />
  );
}
