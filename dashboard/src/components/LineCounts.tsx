// How many lines a change added and removed, such as +12 −3, with a count of
// nothing in gray.
export function LineCounts({
  added,
  removed,
}: Readonly<{ added: number; removed: number }>) {
  return (
    <span className="mono nowrap">
      <span className={added ? "diff-added-count" : "muted"}>+{added}</span>{" "}
      <span className={removed ? "diff-removed-count" : "muted"}>
        −{removed}
      </span>
    </span>
  );
}
