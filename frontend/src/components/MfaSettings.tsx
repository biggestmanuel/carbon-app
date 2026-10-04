/**
 * Enrolling, disabling and reissuing the second factor.
 *
 * Three things this component is careful about, each of which is a way this
 * feature normally loses users:
 *
 * - **Recovery codes are shown once.** Only hashes are stored server-side, so
 *   there is no way to display them again. A "copy" button and a warning that they
 *   will not be shown again are the difference between usable and a support call.
 * - **The seed is not treated as a password field.** It is shown in a readable
 *   monospace block with a copy button, because typing 32 base32 characters by
 *   hand is how enrolment gets abandoned halfway.
 * - **A low recovery-code count is surfaced before it reaches zero.** Running out
 *   means losing the account if the phone is lost, and the UI is the only place
 *   that can warn about it in time.
 */
import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import {
  confirmTotpSetup,
  disableTotp,
  errorMessage,
  fetchMfaStatus,
  regenerateRecoveryCodes,
  startTotpSetup,
} from "../api";
import type { MfaSetupResponse } from "../types";
import TotpQr from "./TotpQr";

/** Below this, the user is told to reissue before it matters. */
const LOW_RECOVERY_CODES = 3;

interface MfaSettingsProps {
  /** Shown after disabling, which signs out every device including this one. */
  onDisabled: () => void;
}

type Stage =
  | { kind: "idle" }
  /** Setup started; showing the secret and waiting for a code to confirm. */
  | { kind: "enrolling"; setup: MfaSetupResponse }
  /** Confirmed; the only moment the recovery codes exist to be read. */
  | { kind: "codes"; codes: string[] };

function MfaSettings({ onDisabled }: MfaSettingsProps) {
  const [stage, setStage] = useState<Stage>({ kind: "idle" });
  const [enabled, setEnabled] = useState(false);
  const [codesLeft, setCodesLeft] = useState(0);
  // Until the status is known, the panel says so rather than offering to turn on
  // a factor that might already be armed.
  const [loaded, setLoaded] = useState(false);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Written inline rather than as a named helper the effect could call, because
  // a bare `setState` before an await in an effect body is a cascading render on
  // every mount. setState after the await is fine, and the cancelled flag stops a
  // resolved request from writing to an unmounted component.
  useEffect(() => {
    let cancelled = false;
    fetchMfaStatus()
      .then((status) => {
        if (cancelled) return;
        setEnabled(status.totp_enabled);
        setCodesLeft(status.recovery_codes_remaining);
        setLoaded(true);
      })
      .catch(() => {
        // Leave the panel in its initial state rather than claiming 2FA is off
        // when the answer is unknown: "not on" is an actionable claim, and this
        // panel offers to turn a factor on that may already be armed.
        if (!cancelled) setLoaded(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = async () => {
    try {
      const status = await fetchMfaStatus();
      setEnabled(status.totp_enabled);
      setCodesLeft(status.recovery_codes_remaining);
      setLoaded(true);
    } catch {
      setLoaded(false);
    }
  };

  const beginSetup = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setStage({ kind: "enrolling", setup: await startTotpSetup() });
    } catch (err) {
      setError(errorMessage(err, "Could not start two-factor setup."));
    } finally {
      setBusy(false);
    }
  };

  const confirmSetup = async () => {
    if (stage.kind !== "enrolling") return;
    setBusy(true);
    setError("");
    try {
      const res = await confirmTotpSetup(stage.setup.secret, code.trim());
      setEnabled(true);
      setCode("");
      // Only ever shown here. Nothing can retrieve these again.
      setStage({ kind: "codes", codes: res.recovery_codes });
      await refresh();
    } catch (err) {
      setError(errorMessage(err, "That code is not valid."));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  const turnOff = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await disableTotp(code.trim(), password);
      onDisabled();
    } catch (err) {
      setError(errorMessage(err, "Could not turn off two-factor authentication."));
    } finally {
      setBusy(false);
    }
  };

  const reissue = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const codes = await regenerateRecoveryCodes(password);
      setPassword("");
      setStage({ kind: "codes", codes });
      await refresh();
    } catch (err) {
      setError(errorMessage(err, "Could not issue new recovery codes."));
    } finally {
      setBusy(false);
    }
  };

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setMessage(`${what} copied to the clipboard.`);
      setError("");
    } catch {
      // Clipboard access needs a secure context and can be refused outright, so
      // the text stays selectable rather than relying on this having worked.
      setError(`Could not copy automatically. Select the ${what.toLowerCase()} and copy it.`);
    }
  };

  // --- Recovery codes, the only time they are ever visible ---------------
  if (stage.kind === "codes") {
    return (
      <div className="card">
        <h2>Save your recovery codes</h2>
        <p className="hint">
          Each code works once. They are shown now and never again &mdash; only
          hashes are stored, so we cannot show them a second time. Keep them
          somewhere you can reach without your phone.
        </p>
        <ul className="recovery-codes">
          {stage.codes.map((value) => (
            <li key={value}>
              <code>{value}</code>
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="secondary"
          onClick={() => void copy(stage.codes.join("\n"), "Recovery codes")}
        >
          Copy all codes
        </button>
        <button type="button" onClick={() => setStage({ kind: "idle" })}>
          I have saved them
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

  // --- Enrolment in progress ---------------------------------------------
  if (stage.kind === "enrolling") {
    const { setup } = stage;
    return (
      <div className="card">
        <h2>Scan this code</h2>
        <p className="hint">
          Open {setup.issuer}, add an account, and scan the code below. Then enter
          the {setup.digits}-digit code it shows to confirm.
        </p>
        {/* Drawn in the browser. See TotpQr: the URI carries the seed, so sending
            it to a hosted QR service would leak the second factor. */}
        <TotpQr
          value={setup.provisioning_uri}
          label={`QR code for ${setup.issuer} two-factor setup`}
        />
        <p className="hint">Or enter this key by hand:</p>
        <div className="totp-secret">
          <code>{setup.secret}</code>
          <button
            type="button"
            className="link"
            onClick={() => void copy(setup.secret, "Setup key")}
          >
            Copy key
          </button>
        </div>
        <label htmlFor="mfa-setup-code">
          Code from your app ({setup.digits} digits)
        </label>
        <input
          id="mfa-setup-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setCode(e.target.value)}
        />
        <button type="button" disabled={busy || code.trim().length === 0} onClick={() => void confirmSetup()}>
          {busy ? "Confirming..." : "Confirm and turn on"}
        </button>
        <button
          type="button"
          className="link"
          disabled={busy}
          onClick={() => {
            setCode("");
            setError("");
            setStage({ kind: "idle" });
          }}
        >
          Cancel
        </button>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  // --- The panel itself ---------------------------------------------------
  return (
    <div className="card">
      <h2>Two-factor authentication</h2>
      {!loaded ? (
        <p className="hint">Checking whether two-factor authentication is on...</p>
      ) : !enabled ? (
        <>
          <p className="hint">
            Require a code from an authenticator app in addition to your
            password. Strongly recommended: a password on its own is only as
            strong as the last place you typed it.
          </p>
          <button type="button" disabled={busy} onClick={() => void beginSetup()}>
            {busy ? "Starting..." : "Set up two-factor authentication"}
          </button>
        </>
      ) : (
        <>
          <p className="info">Two-factor authentication is on.</p>
          {codesLeft > 0 && codesLeft <= LOW_RECOVERY_CODES && (
            <p className="hint">
              Only {codesLeft} recovery {codesLeft === 1 ? "code" : "codes"} left.
              Issue a new set before you run out.
            </p>
          )}
          {codesLeft === 0 && (
            <p className="error">
              You have no recovery codes. If you lose your phone you will need to
              reset your password, which signs out every device.
            </p>
          )}

          <hr />

          <label htmlFor="mfa-reissue-password">
            Password, to issue new recovery codes
          </label>
          <input
            id="mfa-reissue-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)}
          />
          <button
            type="button"
            className="secondary"
            disabled={busy || !password}
            onClick={() => void reissue()}
          >
            {busy ? "Working..." : "Issue new recovery codes"}
          </button>

          <hr />

          <h2>Turn off two-factor authentication</h2>
          <p className="hint">
            Needs a current code and your password, and signs out every device
            including this one. This is the way back in if you lose your phone.
          </p>
          <label htmlFor="mfa-disable-code">Current code or recovery code</label>
          <input
            id="mfa-disable-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setCode(e.target.value)}
          />
          <label htmlFor="mfa-disable-password">Your password</label>
          <input
            id="mfa-disable-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)}
          />
          <button
            type="button"
            className="danger"
            disabled={busy || !code.trim() || !password}
            onClick={() => void turnOff()}
          >
            {busy ? "Turning off..." : "Turn off two-factor authentication"}
          </button>
        </>
      )}
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

export default MfaSettings;