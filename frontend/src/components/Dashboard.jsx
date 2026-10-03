import React, { useState } from "react";
import FootprintForm from "./FootprintForm.jsx";
import Summary from "./Summary.jsx";
import HistoryList from "./HistoryList.jsx";

function Dashboard({ username, onLogout }) {
  // Bumped after a save so Summary and HistoryList refetch without prop drilling.
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="dashboard">
      <header>
        <h1>Carbon Footprint</h1>
        {username && <span className="who">Signed in as {username}</span>}
        <button type="button" className="secondary" onClick={onLogout}>
          Log out
        </button>
      </header>

      <div className="columns">
        <div>
          <FootprintForm onSaved={() => setRefreshKey((n) => n + 1)} />
          <HistoryList refreshKey={refreshKey} />
        </div>
        <Summary refreshKey={refreshKey} />
      </div>
    </div>
  );
}

export default Dashboard;