import { useState } from "react";
import type { MeResponse } from "../types";
import FootprintForm from "./FootprintForm";
import Summary from "./Summary";
import HistoryList from "./HistoryList";
import Sessions from "./Sessions";
import AccountSettings from "./AccountSettings";
import MfaSettings from "./MfaSettings";
import VerifyEmail from "./VerifyEmail";

interface DashboardProps {
  username: string;
  account: MeResponse | null;
  onLogout: () => void;
  onAccountDeleted: () => void;
  onAccountChanged: () => void;
}

function Dashboard({
  username,
  account,
  onLogout,
  onAccountDeleted,
  onAccountChanged,
}: DashboardProps) {
  // Bumped after a change so the panels refetch without prop drilling.
  const [refreshKey, setRefreshKey] = useState(0);
  const [showSettings, setShowSettings] = useState(false);

  const bump = () => setRefreshKey((n) => n + 1);

  return (
    <div className="dashboard">
      <header>
        <h1>Carbon Footprint</h1>
        {username && <span className="who">Signed in as {username}</span>}
        <button
          type="button"
          className="secondary"
          onClick={() => setShowSettings((v) => !v)}
        >
          {showSettings ? "Hide settings" : "Settings"}
        </button>
        <button type="button" className="secondary" onClick={onLogout}>
          Log out
        </button>
      </header>

      {/* No point nagging about a verified address that no longer exists. */}
      {account && !account.has_email && <VerifyEmail verified onVerified={onAccountChanged} />}
      {account && account.has_email && !account.email_verified && (
        <VerifyEmail
          email={account.email}
          verified={account.email_verified}
          onVerified={onAccountChanged}
        />
      )}

      {/* Capture and totals sit side by side. */}
      <div className="columns">
        <FootprintForm onSaved={bump} />
        <Summary refreshKey={refreshKey} />
      </div>

      {/* History spans the full width. Inside the two-column grid it was
          squeezed to about 470px, narrower than its own minimum content width,
          so the columns spilled out past the card border. */}
      <HistoryList refreshKey={refreshKey} />

      <Sessions refreshKey={refreshKey} />

      {showSettings && (
        <>
          {/* Disabling 2FA signs out every device, including this one, so the
              app has to be told rather than left showing a dashboard whose
              cookies no longer work. */}
          <MfaSettings onDisabled={onAccountDeleted} />
          <AccountSettings onDeleted={onAccountDeleted} />
        </>
      )}
    </div>
  );
}

export default Dashboard;
