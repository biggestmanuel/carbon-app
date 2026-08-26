import React, { useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "../config";

function Login({ setToken }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const handleLogin = async () => {
    setError("");
    try {
      const res = await axios.post(`${API_BASE_URL}/auth/login`, {
        username,
        password,
      });
      setToken(res.data.access_token);
    } catch (err) {
      const msg = err.response?.data?.msg || "Login failed. Please try again.";
      setError(msg);
    }
  };

  return (
    <div>
      <h2>Login</h2>
      <input placeholder="Username" onChange={e => setUsername(e.target.value)} />
      <input type="password" placeholder="Password" onChange={e => setPassword(e.target.value)} />
      <button onClick={handleLogin}>Login</button>
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}

export default Login;
