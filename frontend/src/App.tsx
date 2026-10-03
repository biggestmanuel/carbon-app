import { useCallback, useEffect, useState } from "react";
import type { MeResponse } from "./types";
import Login from "./components/Login";
import Register from "./components/Register";
import ForgotPassword from "./components/ForgotPassword";
import ResetPassword from "./components/ResetPassword";
import { VerifyEmailPage } from "./components/VerifyEmail";
import Dashboard from "./components/Dashboard";
import { api, fetchSession, setSessionExpiredHandler } from "./api";

type Mode = "login" | "forgot";
type Route = "verify" | "reset" | "home";

/**
 * Which screen an emailed link should open, decided once at mount.
 *
 * Both links point at a real path the dev server answers with index.html. A bare
 * ?token= on any other path is treated as a reset, because that is what the
 * development-only shortcut link produces.
 */
function initialRoute(): Route {
  const path = window.location.pathname;
  if (path.startsWith("/verify-email")) return "verify";
  if (path.startsWith("/reset-password")) return "reset";
  if (new URLSearchParams(window.location.search).has("token")) return "reset";
  return "home";
}

/**
 * The signed-out / signed-in screens.
 *
 * Split out from App so the emailed-link pages skip the session probe entirely:
 * nobody is logged in on the device that clicks such a link, so asking would
 * only produce a misleading 401 to swallow.
 */
function Home() {
  const [account, setAccount] = useState<MeResponse | null>(null);
  const [checking, setChecking] = useState(true);
  const [sessionError, setSessionError] = useState("");
  const [info, setInfo] = useState("");
  // "login" shows register + login; "forgot" swaps in the reset request form.
  const [mode, setMode] = useState<Mode>("login");

  const handleLogout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // Even if the call fails, drop to the login screen locally.
    }
    setAccount(null);
    setSessionError("");
  }, []);

  // Ask the backend whether the cookie is still a valid session.
  useEffect(() => {
    let cancelled = false;

    fetchSession()
      .then((user) => {
        if (!cancelled) setAccount(user);
      })
      .catch(() => {
        // No session, or it expired. The login screen is the correct outcome,
        // and fetchSession is flagged so this 401 does not also raise the
        // "session has ended" banner.
      })
      .finally(() => {
        // Must clear on success too, or a valid session hangs on the spinner.
        if (!cancelled) setChecking(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Fires when the API layer can no longer recover the session.
  useEffect(() => {
    setSessionExpiredHandler((message: string) => {
      setAccount(null);
      setChecking(false);
      setSessionError(message || "Your session has ended. Please log in again.");
    });
    return () => setSessionExpiredHandler(null);
  }, []);

  const refreshAccount = useCallback(async () => {
    try {
      setAccount(await fetchSession());
    } catch {
      // Leave the previous value; the next render will retry.
    }
  }, []);

  if (checking) {
    return (
      <main className="app">
        <p className="hint">Checking your session...</p>
      </main>
    );
  }

  if (!account) {
    return (
      <main className="app">
        <h1>Carbon Footprint App</h1>
        <p className="hint">Track the emissions from your travel, energy and meals.</p>

        {sessionError && (
          <p className="error" role="alert">
            {sessionError}
          </p>
        )}
        {info && (
          <p className="info" role="status">
            {info}
          </p>
        )}

        {mode === "forgot" ? (
          <ForgotPassword onBack={() => setMode("login")} />
        ) : (
          <div className="columns">
            <Register
              onRegistered={(name, hasEmail) => {
                setSessionError("");
                setInfo(
                  hasEmail
                    ? `Account "${name}" created. Check your email to confirm it, then log in.`
                    : `Account "${name}" created. You can log in now.`
                );
              }}
            />
            <div>
              <Login
                onAuthenticated={(name) => {
                  setInfo("");
                  setSessionError("");
                  // The username is already known, so show the dashboard at once
                  // and reconcile with the server response behind it. That
                  // avoids a blank "checking your session" flash on login.
                  setAccount({ id: 0, username: name, has_email: false, email_verified: false });
                  void refreshAccount();
                }}
              />
              <button
                type="button"
                className="link"
                onClick={() => {
                  setInfo("");
                  setSessionError("");
                  setMode("forgot");
                }}
              >
                Forgotten your password?
              </button>
            </div>
          </div>
        )}
      </main>
    );
  }

  return (
    <main className="app">
      <Dashboard
        username={account.username}
        account={account}
        onLogout={() => void handleLogout()}
        onAccountDeleted={() => {
          setAccount(null);
          setSessionError("");
        }}
        onAccountChanged={() => void refreshAccount()}
      />
    </main>
  );
}

function App() {
  // Decided once: navigating in-app should not need a history listener, and an
  // emailed link is always a fresh page load anyway.
  const [route] = useState<Route>(initialRoute);

  if (route === "verify") {
    return (
      <main className="app">
        <h1>Carbon Footprint App</h1>
        <VerifyEmailPage />
      </main>
    );
  }

  if (route === "reset") {
    return (
      <main className="app">
        <h1>Carbon Footprint App</h1>
        <ResetPassword />
      </main>
    );
  }

  return <Home />;
}

export default App;
