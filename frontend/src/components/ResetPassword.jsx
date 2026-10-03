import { useState } from "react";
import { api, errorMessage } from "../api";

/**
 * Password reset, driven by ?token=... from the emailed link.
 *
 * The backend deliberately returns the same message for an unknown, wrong and
 * expired token, so this screen never says which case it was.
 */
function ResetPassword() {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Read from the URL once, on mount.
  const token = new URLSearchParams(window.location.search).get("token") || "";

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    setError("");

    if (!token) {
      setError("This reset link is invalid or has expired.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/auth/reset-password", { token, password });
      setDone(true);
    } catch (err) {
      setError(errorMessage(err, "This reset link is invalid or has expired."));
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="card">
        <h2>Password updated</h2>
        <p className="hint">You can now log in with your new password.</p>
      </div>
    );
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Choose a new password</h2>

      <label htmlFor="reset-password">Choose password</label>
      <input
        id="reset-password"
        type="password"
        autoComplete="new-password"
        minLength={8}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />

      <label htmlFor="reset-confirm">Confirm new password</label>
      <input
        id="reset-confirm"
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
      />

      <button type="submit" disabled={submitting}>
        {submitting ? "Updating..." : "Update password"}
      </button>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export default ResetPassword;