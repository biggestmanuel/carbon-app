import React, { useCallback, useEffect, useState } from "react";
import Login from "./components/Login.jsx";
import Register from "./components/Register.jsx";
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

        <div className="columns">
          <Register
            onRegistered={(name) => {
              setSessionError("");
              setInfo(`Account "${name}" created. You can log in now.`);
            }}
          />
          <Login
            onAuthenticated={(name) => {
              setInfo("");
              setSessionError("");
              setUsername(name);
            }}
          />
        </div>
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