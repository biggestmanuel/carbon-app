import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import type { FootprintEntry, HistoryResponse } from "../types";

/**
 * The date is formatted without seconds and with a fixed locale because it is
 * the widest cell in the table, and its width must not vary between rows.
 */
function formatDate(iso: string | null): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  // Two-digit year keeps the column narrow; this is a personal tracker where
  // entries span months, not decades.
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

const REGION_LABELS: Record<string, string> = {
  world: "World",
  us: "US",
  eu: "EU",
  gb: "UK",
  fr: "France",
  de: "Germany",
  in: "India",
  ca: "Canada",
  au: "Australia",
  br: "Brazil",
};

interface HistoryListProps {
  refreshKey: number;
}

function HistoryList({ refreshKey }: HistoryListProps) {
  const [entries, setEntries] = useState<FootprintEntry[]>([]);
  const [totalEntries, setTotalEntries] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    // setState is only called after the await, never synchronously in the
    // effect body: doing so triggers a cascading render on every mount.
    (async () => {
      try {
        const res = await api.get<HistoryResponse>("/footprint/history", {
          params: { limit: 25 },
        });
        if (cancelled) return;
        // Guard the shape: a partial or unexpected payload must render an empty
        // table rather than throwing on entries.length.
        setEntries(Array.isArray(res.data?.entries) ? res.data.entries : []);
        setTotalEntries(res.data?.total_entries ?? 0);
        setError("");
      } catch (err) {
        if (!cancelled) setError(errorMessage(err, "Could not load history."));
      } finally {
        // Only the first load shows a spinner. A refresh keeps the previous rows
        // visible instead of flashing an empty table.
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

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
      {/* The wrapper is what keeps the table inside the card: the table has a
          minimum content width, so on narrow viewports this scrolls rather than
          painting past the border. */}
      <div className="table-scroll">
        <table>
          <caption className="sr-only">Saved footprint entries, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Region</th>
              <th scope="col">Car km</th>
              <th scope="col">kWh</th>
              <th scope="col">Meat</th>
              <th scope="col">Plant</th>
              <th scope="col">
                Total
                <span className="unit"> kg CO₂e</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td className="date">{formatDate(entry.created_at)}</td>
                {/* Short label to keep the column narrow; the code is on hover. */}
                <td title={entry.region || undefined}>
                  {REGION_LABELS[entry.region] ?? entry.region ?? "-"}
                </td>
                <td>{entry.car_km}</td>
                <td>{entry.electricity_kwh}</td>
                <td>{entry.meat_meals}</td>
                <td>{entry.plant_meals}</td>
                <td>
                  {/* Rounded for display; the stored total keeps full precision. */}
                  <strong>{Math.round(entry.total * 100) / 100}</strong>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default HistoryList;
