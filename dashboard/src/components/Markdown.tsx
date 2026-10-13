import type { Root } from "mdast";
import { findAndReplace } from "mdast-util-find-and-replace";
import ReactMarkdown, { type Components } from "react-markdown";
import { Link } from "react-router";
import remarkGfm from "remark-gfm";
import { claimPage } from "../paths";

// A claim's id, or an evaluation's copy of one, such as CLM-1003 or CLM-1104-E7.
const CLAIM_ID = /\bCLM-\d{4}(?:-E\d+)?\b/g;

// Makes each claim id in the text a link to the claim's page, except in a link
// already, which can't hold another.
function linkClaims() {
  return (tree: Root) => {
    findAndReplace(
      tree,
      [
        CLAIM_ID,
        (claimId: string) => ({
          type: "link",
          url: claimPage(claimId),
          children: [{ type: "text", value: claimId }],
        }),
      ],
      { ignore: ["link", "linkReference"] },
    );
  };
}

// A path on the dashboard, such as /claims/CLM-1003, rather than another site,
// which //host also names.
const ownPage = (href: string) =>
  href.startsWith("/") && !href.startsWith("//");

// A link to one of the dashboard's own pages stays in the dashboard; any other
// opens in a tab of its own.
const components: Components = {
  a: ({ href = "", children }) =>
    ownPage(href) ? (
      <Link to={href}>{children}</Link>
    ) : (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    ),
  table: ({ children }) => (
    <div className="answer-table">
      <table>{children}</table>
    </div>
  ),
};

// An answer of the Copilot's, written in Markdown, formatted.
export function Markdown({ text }: Readonly<{ text: string }>) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, linkClaims]}
      components={components}
    >
      {text}
    </ReactMarkdown>
  );
}
