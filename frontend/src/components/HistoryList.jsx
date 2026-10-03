import React, { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";

function HistoryList({ refreshKey }) {
  const [entries, setEntries] = useState([]);
  const [totalEntries, setTotalEntries] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/footprint/history", { params: { limit: 25 } });
      // Guard the shape: a partial or unexpected payload must render an empty
      // table rather than throwing on entries.length.
      setEntries(Array.isArray(res.data?.entries) ? res.data.entries : []);
      setTotalEntries(res.data?.total_entries ?? 0);
      setError("");
    } catch (err) {
      setError(errorMessage(err, "Could not load history."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (loading) return <p className="hint">Loading history...</p>;
  if (error) return <p className="error">{error}</p>;
  if (!entries.length) {
    return <p className="hint">No entries yet. Log your first footprint above.</p>;
  }

  return (
    <div className="card">
      <h2>History</h2>
      <p className="hint">
        Showing {entries.length} of {totalEntries}
      </p>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Car km</th>
            <th>kWh</th>
            <th>Meat</th>
            <th>Plant</th>
            <th>Total kg CO₂e</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id}>
              <td>{entry.created_at ? new Date(entry.created_at).toLocaleString() : "-"}</td>
              <td>{entry.car_km}</td>
              <td>{entry.electricity_kwh}</td>
              <td>{entry.meat_meals}</td>
              <td>{entry.plant_meals}</td>
              <td>
                <strong>{entry.total}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default HistoryList;