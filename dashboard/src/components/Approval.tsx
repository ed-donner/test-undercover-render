import { dateTime, NO_APPROVAL_NEEDED } from "../format";

// Who approved a version or a recipe and when, or that nobody needed to.
export function Approval({
  by,
  at,
}: Readonly<{ by: string | null; at: string | null }>) {
  if (!by || !at) return <>{NO_APPROVAL_NEEDED}</>;
  return (
    <>
      {by}, <span className="nowrap">{dateTime(at)}</span>
    </>
  );
}
