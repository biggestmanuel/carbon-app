import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import type { SessionsResponse, SessionRow } from "../types";

interface SessionsProps {
  refreshKey: number;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "unknown";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "unknown";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

function Sessions({ refreshKey }: SessionsProps) {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<SessionsResponse>("/account/sessions")
      .then((res) => {
        if (cancelled) return;
        setSessions(Array.isArray(res.data?.sessions) ? res.data.sessions : []);
        setError("");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorMessage(err, "Could not load sessions."));
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const revoke = async (id: string) => {
    setBusy(id);
    try {
      await api.delete(`/account/sessions/${id}`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setError(errorMessage(err, "Could not revoke that session."));
    } finally {
      setBusy(null);
    }
  };

  const revokeAll = async () => {
    setBusy("all");
    try {
      await api.delete("/account/sessions");
      setSessions([]);
    } catch (err) {
      setError(errorMessage(err, "Could not sign out everywhere."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="card">
      <h2>Active sessions</h2>
      <p className="hint">
        Revoke anything you do not recognise. A session marked new means this
        account had not been used from that browser or address before.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {sessions.length === 0 && !error && <p className="hint">No other active sessions.</p>}

      <ul className="breakdown">
        {sessions.map((s) => (
          <li key={s.id} className={s.unrecognised ? "session-unrecognised" : undefined}>
            <strong>{s.label}</strong>
            {s.unrecognised && (
              <span className="badge">
                {s.new_location && s.new_device
                  ? "new device and location"
                  : s.new_location
                    ? "new location"
                    : "new device"}
              </span>
            )}
            {s.current ? " (this device)" : ""} · {relativeTime(s.last_seen_at)}
            {s.ip_address ? ` · ${s.ip_address}` : ""}
            {!s.current && (
              <button
                type="button"
                className="link"
                disabled={busy === s.id}
                onClick={() => void revoke(s.id)}
              >
                {busy === s.id ? "Revoking..." : "Revoke"}
              </button>
            )}
          </li>
        ))}
      </ul>

      {sessions.length > 1 && (
        <button
          type="button"
          className="secondary"
          disabled={busy === "all"}
          onClick={() => void revokeAll()}
        >
          {busy === "all" ? "Signing out..." : "Sign out everywhere"}
        </button>
      )}
    </div>
  );
}

export default Sessions;