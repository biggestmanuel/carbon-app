import React, { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

const FIELDS = [
  { key: "carKm", label: "Car km", apiKey: "car_km", breakdownKey: "car", unit: "km", step: "0.1" },
  { key: "electricity", label: "Electricity", apiKey: "electricity_kwh", breakdownKey: "electricity", unit: "kWh", step: "0.1" },
  { key: "meatMeals", label: "Meat meals", apiKey: "meat_meals", breakdownKey: "meat", unit: "meals", step: "1" },
  { key: "plantMeals", label: "Plant meals", apiKey: "plant_meals", breakdownKey: "plant", unit: "meals", step: "1" },
];

const EMPTY = { carKm: "", electricity: "", meatMeals: "", plantMeals: "" };

/**
 * Turn a form string into a number the backend will accept.
 *
 * The old version called parseFloat directly, so an empty field became NaN,
 * which axios serialised to `null` and the backend rejected with the
 * unhelpful "All fields must be numbers".
 */
export function parseField(field, raw) {
  const trimmed = String(raw).trim();
  if (trimmed === "") return { value: 0 }; // blank means "none this period"

  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { error: `${field.label} must be a number.` };
  }
  if (value < 0) {
    return { error: `${field.label} cannot be negative.` };
  }
  if (field.step === "1" && !Number.isInteger(value)) {
    return { error: `${field.label} must be a whole number.` };
  }
  return { value };
}

function FootprintForm({ onSaved }) {
  const [values, setValues] = useState(EMPTY);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Factors come from the backend so grid intensity is never hardcoded here.
  const [catalogue, setCatalogue] = useState(null);
  const [region, setRegion] = useState("world");

  useEffect(() => {
    let cancelled = false;
    api
      .get("/footprint/factors")
      .then((res) => {
        if (cancelled) return;
        setCatalogue(res.data);
        setRegion(res.data.default_region);
      })
      .catch(() => {
        // Fall back to the world default; /calculate validates server-side.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChange = (key) => (e) => {
    setValues((prev) => ({ ...prev, [key]: e.target.value }));
    setError("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    setError("");
    setResult(null);

    const payload = { region };
    for (const field of FIELDS) {
      const { value, error: fieldError } = parseField(field, values[field.key]);
      if (fieldError) {
        setError(fieldError);
        return;
      }
      payload[field.apiKey] = value;
    }

    setSubmitting(true);
    try {
      const res = await api.post("/footprint/calculate", payload);
      setResult(res.data);
      setValues(EMPTY);
      onSaved?.(res.data);
    } catch (err) {
      setError(errorMessage(err, "Could not calculate the footprint."));
    } finally {
      setSubmitting(false);
    }
  };

  // Per-unit factors for the currently selected region, once known. Guard the
  // lookup on the array existing: a malformed or partial /factors response must
  // not throw while rendering the form.
  const regions = Array.isArray(catalogue?.regions) ? catalogue.regions : [];
  const activeFactors = catalogue
    ? {
        car: 0.21,
        electricity:
          regions.find((r) => r.code === region)?.electricity_kwh ?? 0,
        meat: 5.0,
        plant: 2.0,
      }
    : null;

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Log your footprint</h2>
      <p className="hint">Leave a field blank to count it as zero.</p>

      <div className="field">
        <label htmlFor="fp-region">Your grid region</label>
        <select
          id="fp-region"
          value={region}
          onChange={(e) => setRegion(e.target.value)}
          disabled={!catalogue}
        >
          {(regions.length > 0
            ? regions
            : [{ code: "world", label: "World average" }]
          ).map((r) => (
            <option key={r.code} value={r.code}>
              {r.label}
            </option>
          ))}
        </select>
        <small>Electricity emissions depend on how dirty the local grid is.</small>
      </div>

      <div className="grid">
        {FIELDS.map((field) => {
          const factor = activeFactors?.[field.breakdownKey];
          return (
            <div key={field.key} className="field">
              <label htmlFor={`fp-${field.key}`}>
                {field.label} ({field.unit})
              </label>
              <input
                id={`fp-${field.key}`}
                name={field.key}
                type="number"
                inputMode="decimal"
                step={field.step}
                min="0"
                placeholder="0"
                value={values[field.key]}
                onChange={handleChange(field.key)}
              />
              {factor !== undefined && (
                <small>{factor} kg CO₂e per {field.unit.replace(/s$/, "")}</small>
              )}
            </div>
          );
        })}
      </div>

      <button type="submit" disabled={submitting}>
        {submitting ? "Calculating..." : "Calculate"}
      </button>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="result" role="status">
          <strong>{result.total} kg CO₂e</strong>
          <ul className="breakdown">
            {FIELDS.map((field) => (
              <li key={field.key}>
                {field.label}: {result.breakdown?.[field.breakdownKey] ?? 0} kg
              </li>
            ))}
          </ul>
          {catalogue && result.factors_version !== catalogue.factors_version && (
            <p className="hint">
              Calculated with factor set v{result.factors_version}; the current set is v
              {catalogue.factors_version}.
            </p>
          )}
        </div>
      )}
    </form>
  );
}

export default FootprintForm;