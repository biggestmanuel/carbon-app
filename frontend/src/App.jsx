import { useCallback, useEffect, useState } from "react";
import Login from "./components/Login.jsx";
import Register from "./components/Register.jsx";
import ForgotPassword from "./components/ForgotPassword.jsx";
import ResetPassword from "./components/ResetPassword.jsx";
import Dashboard from "./components/Dashboard.jsx";
import { api, fetchSession, setSessionExpiredHandler } from "./api";

function App() {
  // There is no token in localStorage to read synchronously any more: the
  // session lives in an httpOnly cookie. So every load asks the backend who we
  // are, and only then decides which screen to render.
  const [username, setUsername] = useState(null);
  const [checking, setChecking] = useState(true);
  const [sessionError, setSessionError] = useState("");
  const [info, setInfo] = useState("");
  // "login" shows register + login; "forgot" swaps in the reset request form.
  const [mode, setMode] = useState("login");

  // Read once at mount: an emailed link arrives with ?token=...
  const [onResetPage] = useState(
    () => new URLSearchParams(window.location.search).has("token")
  );

  const handleLogout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // Even if the call fails, drop to the login screen locally.
    }
    setUsername(null);
    setSessionError("");
  }, []);

  // Ask the backend whether the cookie is still a valid session.
  useEffect(() => {
    let cancelled = false;

    fetchSession()
      .then((user) => {
        if (!cancelled) setUsername(user.username);
      })
      .catch(() => {
        // No session, or it expired. Login screen is the correct outcome.
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Fires when the API layer can no longer recover the session.
  useEffect(() => {
    setSessionExpiredHandler((message) => {
      setUsername(null);
      setChecking(false);
      setSessionError(message || "Your session has ended. Please log in again.");
    });
    return () => setSessionExpiredHandler(null);
  }, []);

  // A link from an email lands on /reset-password?token=...; show that form
  // regardless of session state, since the user is not logged in here.
  if (onResetPage) {
    return (
      <main className="app">
        <h1>Carbon Footprint App</h1>
        <ResetPassword />
      </main>
    );
  }

  if (checking) {
    return (
      <main className="app">
        <p className="hint">Checking your session...</p>
      </main>
    );
  }

  if (!username) {
    return (
      <main className="app">
        <h1>Carbon Footprint App</h1>
        <p className="hint">Track the emissions from your travel, energy and meals.</p>

        {sessionError && (
          <p className="error" role="alert">
            {sessionError}
          </p>
        )}
        {info && <p className="info">{info}</p>}

        {mode === "forgot" ? (
          <ForgotPassword onBack={() => setMode("login")} />
        ) : (
          <div className="columns">
            <Register
              onRegistered={(name, hasEmail) => {
                setSessionError("");
                setInfo(
                  hasEmail
                    ? `Account "${name}" created. You can log in now.`
                    : `Account "${name}" created. Add an email next time if you want to reset your password.`
                );
              }}
            />
            <div>
              <Login
                onAuthenticated={(name) => {
                  setInfo("");
                  setSessionError("");
                  setUsername(name);
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
      <Dashboard username={username} onLogout={handleLogout} />
    </main>
  );
}

export default App;