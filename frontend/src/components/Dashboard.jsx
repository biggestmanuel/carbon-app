import { useState } from "react";
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

      {/* Capture and totals sit side by side. */}
      <div className="columns">
        <FootprintForm onSaved={() => setRefreshKey((n) => n + 1)} />
        <Summary refreshKey={refreshKey} />
      </div>

      {/* History spans the full width. In a two-column grid it was squeezed to
          about 470px, which is narrower than its own minimum content width, so
          the columns spilled out of the card. */}
      <HistoryList refreshKey={refreshKey} />
    </div>
  );
}

export default Dashboard;