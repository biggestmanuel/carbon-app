/**
 * Field definitions, input parsing and factor lookup, all pure.
 *
 * Kept out of the component so the logic can be tested directly: a DOM test
 * cannot reach it, because type="number" inputs reject the very values
 * parseField exists to catch.
 */
import { describe, it, expect } from "vitest";
import {
  buildPayload,
  factorsForRegion,
  parseField,
  EMPTY_VALUES,
  FIELDS,
  FALLBACK_FACTORS,
} from "./footprint";
import type { FieldSpec } from "./footprint";
import { makeFactorsCatalogue } from "../test/api-mock";

const car = FIELDS.find((f) => f.key === "carKm") as FieldSpec;
const meals = FIELDS.find((f) => f.key === "meatMeals") as FieldSpec;

// France and India carry their own car figures so the travel-region behaviour is
// testable; everything else falls back to the shared default.
const CATALOGUE = makeFactorsCatalogue({
  carFactors: { fr: 0.15, in: 0.18 },
});

describe("parseField", () => {
  it("reads a blank as zero, not NaN", () => {
    // The regression. parseFloat("") is NaN, axios serialises NaN to null, and
    // the backend rejected it with "All fields must be numbers".
    expect(parseField(car, "")).toEqual({ ok: true, value: 0 });
    expect(parseField(car, "   ")).toEqual({ ok: true, value: 0 });
  });

  it("accepts valid numbers and numeric strings", () => {
    expect(parseField(car, "100")).toEqual({ ok: true, value: 100 });
    expect(parseField(car, "12.5")).toEqual({ ok: true, value: 12.5 });
    expect(parseField(car, 0)).toEqual({ ok: true, value: 0 });
  });

  it("refuses non-finite input rather than passing it on", () => {
    // Both reach the database as garbage that later poisons every total
    // computed from the row.
    for (const bad of ["abc", Number.NaN, Number.POSITIVE_INFINITY]) {
      const result = parseField(car, bad);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.error).toMatch(/finite number/i);
    }
  });

  it("rejects negatives", () => {
    const result = parseField(car, "-500");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(/cannot be negative/i);
  });

  it("requires whole numbers for meal counts", () => {
    const fractional = parseField(meals, "2.7");
    expect(fractional.ok).toBe(false);
    if (!fractional.ok) expect(fractional.error).toMatch(/whole number/i);
    expect(parseField(meals, "3")).toEqual({ ok: true, value: 3 });
  });

  it("allows a fractional car distance", () => {
    expect(parseField(car, "12.5")).toEqual({ ok: true, value: 12.5 });
  });
});

describe("buildPayload", () => {
  it("always includes the region", () => {
    expect(buildPayload(EMPTY_VALUES, "fr").payload?.region).toBe("fr");
  });

  it("never sends a travel_region", () => {
    // Car emissions use one global factor, so a travel region cannot change any
    // total. The selector was removed rather than left doing nothing; the
    // backend still accepts the field. See backend/tests/test_travel_region.py.
    const { payload } = buildPayload(EMPTY_VALUES, "gb");
    expect(payload).not.toHaveProperty("travel_region");
  });

  it("sends zeros for blank fields", () => {
    expect(buildPayload(EMPTY_VALUES, "world").payload).toEqual({
      region: "world",
      car_km: 0,
      electricity_kwh: 0,
      meat_meals: 0,
      plant_meals: 0,
    });
  });

  it("reports the first invalid field instead of sending it", () => {
    const out = buildPayload({ ...EMPTY_VALUES, carKm: "-5" }, "world");
    expect(out.payload).toBeUndefined();
    expect(out.error).toMatch(/cannot be negative/i);
  });
});

describe("factorsForRegion", () => {
  it("uses the selected region's electricity factor", () => {
    expect(factorsForRegion(CATALOGUE, "in").electricity).toBe(0.713);
    expect(factorsForRegion(CATALOGUE, "fr").electricity).toBe(0.056);
  });

  it("uses the selected region's car factor", () => {
    // Car factors are region-keyed now, so this is not a global constant.
    expect(factorsForRegion(CATALOGUE, "fr").car).toBe(0.15);
    expect(factorsForRegion(CATALOGUE, "in").car).toBe(0.18);
  });

  it("falls back rather than throwing on a missing catalogue", () => {
    expect(factorsForRegion(null, "world").electricity).toBe(FALLBACK_FACTORS.electricity);
    expect(factorsForRegion({ regions: [] }, "zz").electricity).toBe(FALLBACK_FACTORS.electricity);
  });

  it("falls back for a car factor an older backend omitted", () => {
    const legacy = { regions: [{ code: "fr", electricity_kwh: 0.056 }] };
    expect(factorsForRegion(legacy, "fr").car).toBe(FALLBACK_FACTORS.car);
  });

  it("keeps the diet factors constant across regions", () => {
    for (const region of ["fr", "in", "us", "world"]) {
      const lookup = factorsForRegion(CATALOGUE, region);
      expect(lookup.meat).toBe(FALLBACK_FACTORS.meat);
      expect(lookup.plant).toBe(FALLBACK_FACTORS.plant);
    }
  });
});

describe("field definitions", () => {
  it("gives every field a unique key and api key", () => {
    expect(new Set(FIELDS.map((f) => f.key)).size).toBe(FIELDS.length);
    expect(new Set(FIELDS.map((f) => f.apiKey)).size).toBe(FIELDS.length);
  });

  it("matches the keys the backend expects", () => {
    expect(FIELDS.map((f) => f.apiKey).sort()).toEqual(
      ["car_km", "electricity_kwh", "meat_meals", "plant_meals"].sort()
    );
  });
});