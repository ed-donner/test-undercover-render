import type { ReactNode } from "react";
import { Header } from "./Header";

// Every signed-in page's frame: the header, then the page itself.
export function PageFrame({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <>
      <Header />
      <main className="page">{children}</main>
    </>
  );
}
