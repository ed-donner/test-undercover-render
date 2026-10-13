import { useState } from "react";
import { Navigate, useLocation } from "react-router";
import { signIn } from "../auth";
import { ActionForm } from "../components/ActionForm";
import { Brand } from "../components/Brand";
import { PageHeader } from "../components/PageHeader";
import { type SignInState, useSignedIn } from "../handler";
import { QUEUE } from "../paths";

export function SignInPage() {
  const signedIn = useSignedIn();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  if (signedIn) {
    const from = (location.state as SignInState | null)?.from;
    return <Navigate to={from ?? QUEUE} replace />;
  }

  return (
    <main className="sign-in">
      <p className="brand">
        <Brand />
      </p>
      <section className="panel sign-in-panel">
        <PageHeader
          title="Sign in"
          lead="For UnderCover claims handlers. Ask your manager for an account."
        />
        <ActionForm
          label="Sign in"
          ready={email !== "" && password !== ""}
          action={() => signIn(email, password)}
        >
          <label>
            Email
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
              }}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
            />
          </label>
        </ActionForm>
      </section>
    </main>
  );
}
