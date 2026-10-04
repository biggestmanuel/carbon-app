import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { api, errorMessage } from "../api";
import type { LoginResponse, MfaRequiredResponse } from "../types";
import MfaLogin from "./MfaLogin";

interface LoginProps {
  onAuthenticated: (username: string) => void;
}

type Stage =
  | { kind: "password" }
  /** The password was correct; the session waits on a code. */
  | { kind: "code"; pendingToken: string };

function Login({ onAuthenticated }: LoginProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [stage, setStage] = useState<Stage>({ kind: "password" });

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    setError("");

    if (!username.trim() || !password) {
      setError("Enter a username and password.");
      return;
    }

    setSubmitting(true);
    try {
      // The server sets httpOnly cookies here. Nothing is read from or written to
      // localStorage, so there is no token for this component to store.
      // One request, two possible shapes. Typed as a union, so the branch below
      // is what narrows it and no unchecked property access is needed.
      const res = await api.post<LoginResponse | MfaRequiredResponse>("/auth/login", {
        username: username.trim(),
        password,
      });

      // A second factor is on: the response carries no cookies, only a short
      // pending token. Rendering the code form is the whole of the response --
      // there is nothing to store and no session to carry on with.
      if ("mfa_required" in res.data && res.data.mfa_required) {
        setPassword("");
        setStage({ kind: "code", pendingToken: res.data.pending_token });
        return;
      }

      onAuthenticated("username" in res.data ? res.data.username : username.trim());
    } catch (err) {
      setError(errorMessage(err, "Login failed. Please try again."));
    } finally {
      setSubmitting(false);
    }
  };

  if (stage.kind === "code") {
    return (
      <MfaLogin
        pendingToken={stage.pendingToken}
        onAuthenticated={onAuthenticated}
        onCancel={() => {
          setStage({ kind: "password" });
          setError("");
        }}
      />
    );
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Log in</h2>
      <label htmlFor="login-username">Username</label>
      <input
        id="login-username"
        name="username"
        autoComplete="username"
        value={username}
        onChange={(e: ChangeEvent<HTMLInputElement>) => setUsername(e.target.value)}
      />
      <label htmlFor="login-password">Password</label>
      <input
        id="login-password"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e: ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? "Logging in..." : "Log in"}
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export default Login;