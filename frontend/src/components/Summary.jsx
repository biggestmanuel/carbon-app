import React, { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

const CATEGORY_LABELS = {
  car: "Car travel",
  electricity: "Electricity",
  meat: "Meat meals",
  plant: "Plant meals",
};

function Summary({ refreshKey }) {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .get("/footprint/summary")
      .then((res) => {
        if (!cancelled) {
          setSummary(res.data);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err, "Could not load summary."));
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (error) return <p className="error">{error}</p>;
  if (!summary) return <p className="hint">Loading summary...</p>;

  // Coerce the numbers so a partial payload renders zeros instead of NaN.
  const total = Number(summary.total) || 0;
  const entries = Number(summary.entries) || 0;
  const average = Number(summary.average) || 0;
  const breakdown =
    summary.breakdown && typeof summary.breakdown === "object" ? summary.breakdown : {};

  return (
    <div className="card">
      <h2>Lifetime total</h2>
      <p className="big">{total} kg CO₂e</p>
      <p className="hint">
        {entries} {entries === 1 ? "entry" : "entries"}
        {entries > 0 && ` · average ${average} kg per entry`}
      </p>
      <ul className="breakdown">
        {Object.entries(breakdown).map(([key, value]) => (
          <li key={key}>
            {CATEGORY_LABELS[key] || key}: {value} kg
          </li>
        ))}
      </ul>
    </div>
  );
}

export default Summary;