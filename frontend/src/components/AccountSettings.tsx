import { useState } from "react";
import { api, errorMessage } from "../api";

interface AccountSettingsProps {
  onDeleted: () => void;
}

/**
 * Data export and account deletion.
 *
 * Deletion asks for the password again because a stolen session cookie must not
 * be enough to destroy someone's history.
 */
function AccountSettings({ onDeleted }: AccountSettingsProps) {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);

  // The browser handles the download; the fetch is only to trigger the response.
  const download = async (format: "json" | "csv") => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const res = await api.get(`/account/export?format=${format}`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `carbon-footprint.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setMessage(`Your ${format.toUpperCase()} export is downloading.`);
    } catch (err) {
      setError(errorMessage(err, "Could not export your data."));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.delete("/account/account", { data: { password } });
      onDeleted();
    } catch (err) {
      setError(errorMessage(err, "Could not delete the account."));
    } finally {
      setBusy(false);
    }
  };

  const armed = confirmText.trim().toUpperCase() === "DELETE";

  return (
    <div className="card">
      <h2>Your data</h2>

      <p className="hint">Download everything you have logged, including the factors used.</p>
      <button type="button" className="secondary" disabled={busy} onClick={() => void download("json")}>
        Export as JSON
      </button>
      <button type="button" className="secondary" disabled={busy} onClick={() => void download("csv")}>
        Export as CSV
      </button>

      <hr />

      <h2>Delete account</h2>
      <p className="hint">
        This removes your account and every entry permanently. It cannot be undone.
      </p>
      <label htmlFor="del-password">Confirm with your password</label>
      <input
        id="del-password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <label htmlFor="del-confirm">Type DELETE to enable</label>
      <input
        id="del-confirm"
        value={confirmText}
        onChange={(e) => setConfirmText(e.target.value)}
      />
      <button type="button" className="danger" disabled={busy || !armed || !password} onClick={() => void remove()}>
        {busy ? "Deleting..." : "Delete my account"}
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
    </div>
  );
}

export default AccountSettings;