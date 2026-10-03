import { useState } from "react";
import { api, errorMessage } from "../api";

interface VerifyEmailProps {
  /** The server masks the address, so this is for display only. */
  email?: string;
  verified: boolean;
  onVerified: () => void;
}

/**
 * Prompts the user to confirm ownership of their address.
 *
 * Until this is done the account cannot be recovered: the backend refuses to
 * mail a reset link to an unverified address, precisely so a stranger who
 * registered someone else's inbox cannot be handed their account.
 */
function VerifyEmail({ email, verified, onVerified }: VerifyEmailProps) {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);

  if (verified) return null;

  const request = async () => {
    setSending(true);
    setError("");
    setMessage("");
    try {
      const res = await api.post<{ msg: string; dev_token?: string }>(
        "/account/verify-email/request"
      );
      // With delivery off there is no inbox to check, so the link comes back.
      setMessage(
        res.data.dev_token
          ? `Email delivery is off in development. Confirm here: /verify-email?token=${res.data.dev_token}`
          : res.data.msg
      );
    } catch (err) {
      setError(errorMessage(err, "Could not send the confirmation email."));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="card">
      <h2>Confirm your email</h2>
      <p className="hint">
        {email
          ? `Confirm ${email} so you can reset your password if you forget it.`
          : "Add an email address to your profile if you want password recovery."}
      </p>
      <p className="hint">
        Until this is done, a password reset is refused: mailing an unconfirmed
        address would send the link to whoever actually owns that inbox.
      </p>
      <button type="button" className="secondary" disabled={sending} onClick={() => void request()}>
        {sending ? "Sending..." : "Send confirmation link"}
      </button>
      {message && (
        <p className="info" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {message.includes("token=") && (
        <button type="button" className="secondary" onClick={onVerified}>
          I have confirmed it
        </button>
      )}
    </div>
  );
}

/** Confirmation form reached from the emailed link. */
export function VerifyEmailPage() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  const confirm = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/account/verify-email/confirm", { token });
      setDone(true);
    } catch (err) {
      setError(errorMessage(err, "This confirmation link is invalid or has expired."));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="card">
        <h2>Email confirmed</h2>
        <p className="hint">You can now reset your password if you forget it.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Confirm your email</h2>
      <p className="hint">This proves the address belongs to you.</p>
      <button type="button" disabled={busy || !token} onClick={() => void confirm()}>
        {busy ? "Confirming..." : "Confirm this address"}
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default VerifyEmail;