import { useEffect, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { api, errorMessage } from "../api";
import type { CalculateResult, FactorsCatalogue, RegionOption } from "../types";
import { buildPayload, EMPTY_VALUES, factorsForRegion, FIELDS } from "../lib/footprint";

interface FootprintFormProps {
  onSaved?: (result: CalculateResult) => void;
}

/** Shown until /factors resolves, so the labels are never blank. */
const PLACEHOLDER_REGIONS: RegionOption[] = [
  { code: "world", label: "World average", electricity_kwh: 0.475 },
];

function FootprintForm({ onSaved }: FootprintFormProps) {
  const [values, setValues] = useState(EMPTY_VALUES);
  const [error, setError] = useState("");
  const [result, setResult] = useState<CalculateResult | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Factors come from the backend so grid intensity is never hardcoded here.
  const [catalogue, setCatalogue] = useState<FactorsCatalogue | null>(null);
  const [region, setRegion] = useState("world");

  useEffect(() => {
    let cancelled = false;
    api
      .get<FactorsCatalogue>("/footprint/factors")
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

  const handleChange =
    (key: keyof typeof EMPTY_VALUES) =>
    (e: ChangeEvent<HTMLInputElement>) => {
      setValues((prev) => ({ ...prev, [key]: e.target.value }));
      setError("");
    };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    setError("");
    setResult(null);

    // Validate before sending. A blank field is zero, never NaN.
    const { payload, error: payloadError } = buildPayload(values, region);
    if (payloadError !== undefined || payload === undefined) {
      setError(payloadError ?? "Could not read the form.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await api.post<CalculateResult>("/footprint/calculate", payload);
      setResult(res.data);
      setValues(EMPTY_VALUES);
      onSaved?.(res.data);
    } catch (err) {
      setError(errorMessage(err, "Could not calculate the footprint."));
    } finally {
      setSubmitting(false);
    }
  };

  // Guard the shape: a partial or unexpected payload must not throw here.
  const regions = Array.isArray(catalogue?.regions) ? catalogue.regions : [];
  const activeFactors = factorsForRegion(catalogue, region);

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Log your footprint</h2>
      <p className="hint">Leave a field blank to count it as zero.</p>

      <div className="grid">
        <div className="field">
          <label htmlFor="fp-region">Your grid region</label>
          <select
            id="fp-region"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            disabled={!catalogue}
          >
            {(regions.length > 0 ? regions : PLACEHOLDER_REGIONS).map((r) => (
              <option key={r.code} value={r.code}>
                {r.label}
              </option>
            ))}
          </select>
          <small>Electricity emissions depend on how dirty the local grid is.</small>
        </div>
      </div>

      <div className="grid">
        {FIELDS.map((field) => {
          const factor = activeFactors[field.breakdownKey];
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
              <small>
                {factor} kg CO₂e per {field.unit.replace(/s$/, "")}
              </small>
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
                {field.label}: {result.breakdown[field.breakdownKey] ?? 0} kg
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
