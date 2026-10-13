import { Link } from "react-router";
import { claimPage } from "../paths";

export function ClaimLink({ claimId }: Readonly<{ claimId: string }>) {
  return (
    <Link className="mono" to={claimPage(claimId)}>
      {claimId}
    </Link>
  );
}
