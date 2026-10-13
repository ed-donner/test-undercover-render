import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { api } from "../api";
import { HandlerContext, type SignInState, useSignedIn } from "../handler";
import { SIGN_IN } from "../paths";
import { useLoad } from "../useLoad";
import { PageFrame } from "./PageFrame";
import { StateMessage } from "./StateMessage";
import { SignOutButton } from "./SignOutButton";

// Keeps a page to signed-in handlers. A visitor goes to the sign-in page,
// which brings them back here once they have signed in.
export function RequireHandler({
  children,
}: Readonly<{ children: ReactNode }>) {
  const signedIn = useSignedIn();
  const location = useLocation();
  if (signedIn === undefined) return null;
  if (!signedIn) {
    const state: SignInState = { from: location };
    return <Navigate to={SIGN_IN} state={state} replace />;
  }
  return <HandlerProvider>{children}</HandlerProvider>;
}

// Loads the handler signed in for the pages, or says why it can't.
function HandlerProvider({ children }: Readonly<{ children: ReactNode }>) {
  const { data: handler, error } = useLoad(api.getSignedInHandler);
  if (!handler)
    return (
      <PageFrame>
        <StateMessage error={error} />
        {error && <SignOutButton className="button" />}
      </PageFrame>
    );
  return <HandlerContext value={handler}>{children}</HandlerContext>;
}
