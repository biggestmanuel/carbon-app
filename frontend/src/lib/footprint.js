/**
 * Field definitions and input parsing, kept out of the component so the pure
 * logic is testable on its own and fast-refresh can swap the component alone.
 */

export const FIELDS = [
  { key: "carKm", label: "Car km", apiKey: "car_km", breakdownKey: "car", unit: "km", step: "0.1" },
  {
    key: "electricity",
    label: "Electricity",
    apiKey: "electricity_kwh",
    breakdownKey: "electricity",
    unit: "kWh",
    step: "0.1",
  },
  { key: "meatMeals", label: "Meat meals", apiKey: "meat_meals", breakdownKey: "meat", unit: "meals", step: "1" },
  { key: "plantMeals", label: "Plant meals", apiKey: "plant_meals", breakdownKey: "plant", unit: "meals", step: "1" },
];

export const EMPTY_VALUES = { carKm: "", electricity: "", meatMeals: "", plantMeals: "" };

/**
 * Per-unit factors for display only. The authoritative values come from the
 * backend's /footprint/factors endpoint; these are the fallbacks shown before
 * that response arrives, and they match factors.py.
 */
export const FALLBACK_FACTORS = {
  car: 0.21,
  meat: 5.0,
  plant: 2.0,
  electricity: 0.475,
};

/**
 * Turn a form string into a number the backend will accept.
 *
 * The old version called parseFloat directly, so an empty field became NaN,
 * which axios serialised to `null` and the backend rejected with the
 * unhelpful "All fields must be numbers". Blank therefore means zero.
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

/**
 * Build the request body, or return the first validation error found.
 *
 * travelRegion is omitted when blank so the backend applies its own default of
 * "same as home" rather than treating an empty string as a region.
 */
export function buildPayload(values, region, travelRegion = "") {
  const payload = { region };
  if (travelRegion) payload.travel_region = travelRegion;
  for (const field of FIELDS) {
    const { value, error } = parseField(field, values[field.key]);
    if (error) return { error };
    payload[field.apiKey] = value;
  }
  return { payload };
}

/** Display factors for the selected region, tolerating a missing catalogue. */
export function factorsForRegion(catalogue, region) {
  const regions = Array.isArray(catalogue?.regions) ? catalogue.regions : [];
  const selected = regions.find((r) => r.code === region);
  return {
    car: FALLBACK_FACTORS.car,
    electricity: selected?.electricity_kwh ?? FALLBACK_FACTORS.electricity,
    meat: FALLBACK_FACTORS.meat,
    plant: FALLBACK_FACTORS.plant,
  };
}