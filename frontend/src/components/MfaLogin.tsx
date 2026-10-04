/**
 * The second half of a login.
 *
 * Split from Login.tsx because it is a different interaction with different
 * failure modes: the password is already accepted, so a rejection here means the
 * code was wrong rather than the credentials, and the pending token expires
 * whether or not this component is on screen.
 *
 * autoComplete is deliberate. `one-time-code` is what lets iOS and Android offer
 * the code from the authenticator app, which is most of the value of having one.
 */
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { errorMessage, verifySecondFactor } from "../api";

interface MfaLoginProps {
  /** Proves the password step succeeded. Not a session; expires in 5 minutes. */
  pendingToken: string;
  onAuthenticated: (username: string) => void;
  /** Abandon the attempt and go back to the password form. */
  onCancel: () => void;
}

function MfaLogin({ pendingToken, onAuthenticated, onCancel }: MfaLoginProps) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    setError("");

    const trimmed = code.trim();
    if (!trimmed) {
      setError("Enter the code from your authenticator app.");
      return;
    }

    setSubmitting(true);
    try {
      // The server sets the httpOnly session cookies here. Nothing is stored
      // client-side, and the pending token is discarded rather than kept.
      const res = await verifySecondFactor(pendingToken, trimmed);
      onAuthenticated(res.username);
    } catch (err) {
      setError(errorMessage(err, "That code is not valid."));
      // Cleared so a retry cannot send the same spent code: TOTP codes are
      // single-use, so resending one would fail with a message that looks
      // identical to a wrong code.
      setCode("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Two-factor authentication</h2>
      <p className="hint">
        Enter the six-digit code from your authenticator app. You can use a
        recovery code instead if you have lost your phone.
      </p>
      <label htmlFor="mfa-code">Authentication code</label>
      <input
        id="mfa-code"
        name="code"
        inputMode="numeric"
        // Not type="number": that lets a browser accept "1e5" and strips leading
        // zeros, and 000123 is a valid code that must survive intact.
        autoComplete="one-time-code"
        autoFocus
        value={code}
        onChange={(e: ChangeEvent<HTMLInputElement>) => setCode(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? "Checking..." : "Verify"}
      </button>
      <button type="button" className="link" onClick={onCancel} disabled={submitting}>
        Use a different account
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export default MfaLogin;