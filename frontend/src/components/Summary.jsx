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

  return (
    <div className="card">
      <h2>Lifetime total</h2>
      <p className="big">{summary.total} kg CO₂e</p>
      <p className="hint">
        {summary.entries} {summary.entries === 1 ? "entry" : "entries"}
        {summary.entries > 0 && ` · average ${summary.average} kg per entry`}
      </p>
      <ul className="breakdown">
        {Object.entries(summary.breakdown || {}).map(([key, value]) => (
          <li key={key}>
            {CATEGORY_LABELS[key] || key}: {value} kg
          </li>
        ))}
      </ul>
    </div>
  );
}

export default Summary;