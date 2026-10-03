import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { api, errorMessage } from "../api";

interface ForgotPasswordProps {
  onBack: () => void;
}

interface ForgotResponse {
  msg: string;
  dev_token?: string;
}

/**
 * Start a password reset.
 *
 * The backend always answers "if that address exists..." whether it does or not,
 * and refuses unconfirmed addresses with the same wording, so this screen shows
 * that same text no matter what came back. In development the response also
 * carries the token, because there is no inbox to check.
 */
function ForgotPassword({ onBack }: ForgotPasswordProps) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [devToken, setDevToken] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    setError("");

    if (!email.trim()) {
      setError("Enter your email address.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await api.post<ForgotResponse>("/auth/forgot-password", {
        email: email.trim(),
      });
      setSent(true);
      setDevToken(res.data?.dev_token ?? "");
    } catch (err) {
      setError(errorMessage(err, "Could not start the reset. Try again later."));
    } finally {
      setSubmitting(false);
    }
  };

  if (sent) {
    return (
      <div className="card">
        <h2>Check your email</h2>
        <p className="hint">If that address has an account, a reset link is on its way.</p>
        {devToken && (
          <div className="result">
            <strong>Development mode</strong>
            <p className="hint">
              Email delivery is off, so the link was written to the server log:
            </p>
            <a href={`/?token=${encodeURIComponent(devToken)}`}>Open the reset link</a>
          </div>
        )}
        <button type="button" className="secondary" onClick={onBack}>
          Back to log in
        </button>
      </div>
    );
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Reset your password</h2>
      <p className="hint">Works only once the address has been confirmed.</p>
      <label htmlFor="forgot-email">Email</label>
      <input
        id="forgot-email"
        name="email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e: ChangeEvent<HTMLInputElement>) => setEmail(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? "Sending..." : "Send reset link"}
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="button" className="secondary" onClick={onBack}>
        Back to log in
      </button>
    </form>
  );
}

export default ForgotPassword;
