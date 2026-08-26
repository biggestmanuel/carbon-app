import React, { useState } from "react";
import Login from "./components/Login";
import Register from "./components/Register";
import Dashboard from "./components/Dashboard";

function App() {
  const [token, setToken] = useState(() => localStorage.getItem("token"));

  const handleSetToken = (newToken) => {
    if (newToken) {
      localStorage.setItem("token", newToken);
    } else {
      localStorage.removeItem("token");
    }
    setToken(newToken);
  };

  if (!token) {
    return (
      <div>
        <h1>Carbon Footprint App</h1>
        <Register setToken={handleSetToken} />
        <Login setToken={handleSetToken} />
      </div>
    );
  }

  return <Dashboard token={token} onLogout={() => handleSetToken(null)} />;
}

export default App;
