import type { ReactNode } from "react";

// The top of every page: its title, a line on what the page is for when it
// isn't plain from the title, and the page's main action on the right.
export function PageHeader({
  title,
  lead,
  eyebrow,
  status,
  action,
}: Readonly<{
  title: string;
  lead?: ReactNode;
  eyebrow?: ReactNode;
  status?: ReactNode;
  action?: ReactNode;
}>) {
  return (
    <div className="page-header">
      <div className="page-header-text">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <div className="title-row">
          <h1>{title}</h1>
          {status}
        </div>
        {lead && <p className="lead">{lead}</p>}
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </div>
  );
}
