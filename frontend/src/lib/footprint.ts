/** Field definitions, input parsing and factor lookup, all pure. */

export interface FieldSpec {
  key: "carKm" | "electricity" | "meatMeals" | "plantMeals";
  label: string;
  apiKey: "car_km" | "electricity_kwh" | "meat_meals" | "plant_meals";
  breakdownKey: "car" | "electricity" | "meat" | "plant";
  unit: string;
  step: "0.1" | "1";
}

export type FormValues = Record<FieldSpec["key"], string>;

export interface CalculatePayload {
  region: string;
  car_km: number;
  electricity_kwh: number;
  meat_meals: number;
  plant_meals: number;
}

export interface FactorLookup {
  car: number;
  electricity: number;
  meat: number;
  plant: number;
}

export const FIELDS: readonly FieldSpec[] = [
  {
    key: "carKm",
    label: "Car km",
    apiKey: "car_km",
    breakdownKey: "car",
    unit: "km",
    step: "0.1",
  },
  {
    key: "electricity",
    label: "Electricity",
    apiKey: "electricity_kwh",
    breakdownKey: "electricity",
    unit: "kWh",
    step: "0.1",
  },
  {
    key: "meatMeals",
    label: "Meat meals",
    apiKey: "meat_meals",
    breakdownKey: "meat",
    unit: "meals",
    step: "1",
  },
  {
    key: "plantMeals",
    label: "Plant meals",
    apiKey: "plant_meals",
    breakdownKey: "plant",
    unit: "meals",
    step: "1",
  },
] as const;

export const EMPTY_VALUES: FormValues = {
  carKm: "",
  electricity: "",
  meatMeals: "",
  plantMeals: "",
};

/**
 * Either a usable number, or the message explaining why the input was refused.
 *
 * A discriminated union rather than `{ value, error }` so the success branch
 * cannot be read without the type checker confirming an error is absent.
 */
export type ParseResult = { ok: true; value: number } | { ok: false; error: string };

/**
 * Per-unit factors for display only. The authoritative values come from the
 * backend's /footprint/factors endpoint; these are the fallbacks shown before
 * that response arrives, and they match factors.py.
 */
export const FALLBACK_FACTORS: FactorLookup = {
  car: 0.21,
  meat: 5.0,
  plant: 2.0,
  electricity: 0.475,
};

/**
 * Turn a raw field value into a number the backend will accept.
 *
 * The old version called parseFloat directly, so an empty field became NaN,
 * which axios serialised to `null` and the backend rejected with the unhelpful
 * "All fields must be numbers". Blank therefore means zero.
 *
 * Non-finite results are refused explicitly rather than passed on: Infinity
 * and NaN both reach the database as garbage that later breaks every total
 * computed from it.
 */
export function parseField(field: FieldSpec, raw: string | number): ParseResult {
  const trimmed = String(raw).trim();
  if (trimmed === "") return { ok: true, value: 0 }; // blank means "none this period"

  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { ok: false, error: `${field.label} must be a finite number.` };
  }
  if (value < 0) {
    return { ok: false, error: `${field.label} cannot be negative.` };
  }
  if (field.step === "1" && !Number.isInteger(value)) {
    return { ok: false, error: `${field.label} must be a whole number.` };
  }
  return { ok: true, value };
}

/**
 * Build the request body, or return the first validation error found.
 *
 * There is deliberately no travelRegion parameter. The backend still accepts
 * `travel_region`, but car emissions use a single global factor, so the value
 * cannot change any total -- and a control that silently does nothing is worse
 * than no control. See the pinned test in the backend suite.
 */
export function buildPayload(
  values: FormValues,
  region: string
): { payload?: CalculatePayload; error?: string } {
  const parsed: Partial<Record<FieldSpec["apiKey"], number>> = {};

  for (const field of FIELDS) {
    const result = parseField(field, values[field.key]);
    if (!result.ok) return { error: result.error };
    parsed[field.apiKey] = result.value;
  }

  // Every apiKey above is written, so these are never undefined in practice.
  // The fallbacks exist so the payload satisfies its own type without a cast.
  const payload: CalculatePayload = {
    region,
    car_km: parsed.car_km ?? 0,
    electricity_kwh: parsed.electricity_kwh ?? 0,
    meat_meals: parsed.meat_meals ?? 0,
    plant_meals: parsed.plant_meals ?? 0,
  };

  return { payload };
}

/** Display factors for the selected region, tolerating a missing catalogue. */
export function factorsForRegion(
  catalogue: { regions?: readonly { code: string; electricity_kwh: number }[] } | null,
  region: string
): FactorLookup {
  const regions = Array.isArray(catalogue?.regions) ? catalogue.regions : [];
  const selected = regions.find((r) => r.code === region);
  return {
    car: FALLBACK_FACTORS.car,
    electricity: selected?.electricity_kwh ?? FALLBACK_FACTORS.electricity,
    meat: FALLBACK_FACTORS.meat,
    plant: FALLBACK_FACTORS.plant,
  };
}