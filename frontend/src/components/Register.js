import React, { useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "../config";

function Register({ setToken }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const handleRegister = async () => {
    setError("");
    try {
      await axios.post(`${API_BASE_URL}/auth/register`, {
        username,
        password,
      });
      alert("Registered! Now login.");
    } catch (err) {
      const msg = err.response?.data?.msg || "Registration failed. Please try again.";
      setError(msg);
    }
  };

  return (
    <div>
      <h2>Register</h2>
      <input placeholder="Username" onChange={e => setUsername(e.target.value)} />
      <input type="password" placeholder="Password" onChange={e => setPassword(e.target.value)} />
      <button onClick={handleRegister}>Register</button>
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}

export default Register;
