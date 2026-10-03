import React, { useState } from "react";
import { api, errorMessage } from "../api";

// Mirrors the backend's MIN_PASSWORD_LENGTH / USERNAME_RE so the user gets
// an instant answer instead of a round trip.
const MIN_PASSWORD_LENGTH = 8;
const USERNAME_RE = /^[A-Za-z0-9._-]+$/;

function Register({ onRegistered }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const validate = () => {
    const name = username.trim();
    if (name.length < 3) return "Username must be at least 3 characters.";
    if (name.length > 80) return "Username must be at most 80 characters.";
    if (!USERNAME_RE.test(name))
      return "Username may only contain letters, digits, dots, dashes and underscores.";
    if (password.length < MIN_PASSWORD_LENGTH)
      return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
    if (password.length > 128) return "Password must be at most 128 characters.";
    return null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    setError("");

    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/auth/register", { username: username.trim(), password });
      setPassword("");
      onRegistered(username.trim());
    } catch (err) {
      setError(errorMessage(err, "Registration failed. Please try again."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Create account</h2>
      <label htmlFor="reg-username">Username</label>
      <input
        id="reg-username"
        name="username"
        autoComplete="username"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
      />
      <label htmlFor="reg-password">Password</label>
      <input
        id="reg-password"
        name="password"
        type="password"
        autoComplete="new-password"
        minLength={MIN_PASSWORD_LENGTH}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button type="submit" disabled={submitting}>
        {submitting ? "Creating..." : "Register"}
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export default Register;