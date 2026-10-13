import { createContext, use, useEffect, useState } from "react";
import type { Location } from "react-router";
import type { Handler } from "./api";
import { followSession } from "./auth";

// The handler signed in, which RequireHandler provides to the pages it guards.
export const HandlerContext = createContext<Handler | undefined>(undefined);

// Where the sign-in page sends a handler once they have signed in.
export interface SignInState {
  from?: Location;
}

// The handler signed in, for the pages inside RequireHandler.
export function useHandler(): Handler {
  const handler = use(HandlerContext);
  if (!handler) throw new Error("This page needs a signed-in handler");
  return handler;
}

// Whether a handler is signed in, or undefined until Supabase has said.
export function useSignedIn(): boolean | undefined {
  const [signedIn, setSignedIn] = useState<boolean>();
  useEffect(() => followSession(setSignedIn), []);
  return signedIn;
}
