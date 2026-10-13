import type { ReactNode } from "react";
import { Copilot } from "./Copilot";
import { Header } from "./Header";

// Every signed-in page's frame: the header, then the page beside the Copilot's
// sidebar, which opens over the page on a narrow window. The page scrolls on its
// own, and its layouts answer to the width it has.
export function PageFrame({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="app">
      <Header />
      <div className="frame">
        <div className="page-area">
          <main className="page">{children}</main>
        </div>
        <Copilot />
      </div>
    </div>
  );
}
