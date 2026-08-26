import React from "react";
import FootprintForm from "./FootprintForm";

function Dashboard({ token, onLogout }) {
  return (
    <div>
      <h2>Dashboard</h2>
      {onLogout && <button onClick={onLogout}>Log out</button>}
      <FootprintForm token={token} />
    </div>
  );
}

export default Dashboard;
