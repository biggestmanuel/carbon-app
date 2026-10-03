import React, { useState } from "react";
import { api, errorMessage } from "../api";

function Login({ onAuthenticated }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    setError("");

    if (!username.trim() || !password) {
      setError("Enter a username and password.");
      return;
    }

    setSubmitting(true);
    try {
      // The server sets httpOnly cookies here. Nothing is read from or written
      // to localStorage, so there is no token for this component to store.
      const res = await api.post("/auth/login", {
        username: username.trim(),
        password,
      });
      onAuthenticated(res.data.username || username.trim());
    } catch (err) {
      setError(errorMessage(err, "Login failed. Please try again."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Log in</h2>
      <label htmlFor="login-username">Username</label>
      <input
        id="login-username"
        name="username"
        autoComplete="username"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
      />
      <label htmlFor="login-password">Password</label>
      <input
        id="login-password"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? "Logging in..." : "Log in"}
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export default Login;