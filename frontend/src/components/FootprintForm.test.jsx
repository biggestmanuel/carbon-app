/**
 * FootprintForm validation and submission.
 *
 * parseField is the regression that motivated this suite: the original form
 * called parseFloat directly, so an empty input became NaN, axios serialised
 * it to null, and the backend replied with the unhelpful "All fields must be
 * numbers". Blank must mean zero; junk must be refused before any request.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock only the transport so no real request is attempted and the payload can
// be inspected directly. errorMessage is the real implementation, so the
// component's user-facing messages are genuinely under test.
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    api: { post: vi.fn(), get: vi.fn() },
  };
});

import { api } from "../api";
import FootprintForm, { parseField } from "../components/FootprintForm.jsx";

const FACTORS = {
  default_region: "world",
  factors_version: 2,
  regions: [
    { code: "fr", label: "France", electricity_kwh: 0.056 },
    { code: "in", label: "India", electricity_kwh: 0.713 },
    { code: "world", label: "World average", electricity_kwh: 0.475 },
  ],
  units: {},
};

/** Force a value React will accept, including values type=number rejects. */
function setValue(element, value) {
  const proto =
    element.tagName === "SELECT" ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(element, String(value));
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

beforeEach(() => {
  api.get.mockResolvedValue({ data: FACTORS });
  api.post.mockResolvedValue({
    data: {
      total: 146,
      breakdown: { car: 21, electricity: 95, meat: 15, plant: 10 },
      region: "world",
      factors_version: 2,
    },
  });
});

describe("parseField", () => {
  const car = { label: "Car km", step: "0.1" };
  const meals = { label: "Meat meals", step: "1" };

  it("reads a blank as zero, not NaN", () => {
    // This is the regression. parseFloat("") is NaN, axios serialises NaN to
    // null, and the backend rejected it with "All fields must be numbers".
    expect(parseField(car, "")).toEqual({ value: 0 });
    expect(parseField(car, "   ")).toEqual({ value: 0 });
  });

  it("accepts valid numbers and numeric strings", () => {
    expect(parseField(car, "100")).toEqual({ value: 100 });
    expect(parseField(car, "12.5")).toEqual({ value: 12.5 });
    expect(parseField(car, 0)).toEqual({ value: 0 });
  });

  it("rejects non-numeric input", () => {
    expect(parseField(car, "abc").error).toMatch(/must be a number/i);
    expect(parseField(car, NaN).error).toMatch(/must be a number/i);
    expect(parseField(car, Infinity).error).toMatch(/must be a number/i);
    expect(parseField(car, null).error).toMatch(/must be a number/i);
  });

  it("rejects negatives", () => {
    expect(parseField(car, "-500").error).toMatch(/cannot be negative/i);
  });

  it("requires whole numbers for meal counts", () => {
    expect(parseField(meals, "2.7").error).toMatch(/whole number/i);
    expect(parseField(meals, "3")).toEqual({ value: 3 });
  });
});

describe("blank and invalid input", () => {
  it("sends zeros when every field is left blank", async () => {
    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][1]).toEqual({
      region: "world",
      car_km: 0,
      electricity_kwh: 0,
      meat_meals: 0,
      plant_meals: 0,
    });
    // The payload must be JSON-safe: no NaN, no null, no undefined.
    for (const value of Object.values(api.post.mock.calls[0][1])) {
      expect(value === undefined || value === null || Number.isNaN(value)).toBe(false);
    }
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("successful submission", () => {
  it("sends the entered numbers with the selected region", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<FootprintForm onSaved={onSaved} />);

    // Wait for the region catalogue before selecting.
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    const select = await screen.findByLabelText(/grid region/i);

    setValue(document.getElementById("fp-carKm"), "100");
    setValue(document.getElementById("fp-electricity"), "200");
    setValue(document.getElementById("fp-meatMeals"), "3");
    setValue(document.getElementById("fp-plantMeals"), "5");
    setValue(select, "fr");

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0][0]).toBe("/footprint/calculate");
    expect(api.post.mock.calls[0][1]).toEqual({
      region: "fr",
      car_km: 100,
      electricity_kwh: 200,
      meat_meals: 3,
      plant_meals: 5,
    });
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ total: 146 }));
  });

  it("shows the result and its breakdown", async () => {
    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("146 kg CO₂e");
    expect(status).toHaveTextContent(/Car km: 21 kg/);
    expect(status).toHaveTextContent(/Electricity: 95 kg/);
  });

  it("clears the inputs after saving", async () => {
    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    setValue(document.getElementById("fp-carKm"), "100");
    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() => expect(document.getElementById("fp-carKm").value).toBe(""));
  });

  it("reports a server-side validation error", async () => {
    api.post.mockRejectedValue({
      response: { status: 400, data: { msg: "car_km must be a finite number" } },
    });

    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/finite number/i)
    );
  });

  it("explains that the server is unreachable", async () => {
    api.post.mockRejectedValue({ request: {} });

    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/backend running/i)
    );
  });
});

describe("pending state", () => {
  it("disables the button and reports progress while in flight", async () => {
    let release;
    api.post.mockImplementation(() => new Promise((resolve) => { release = resolve; }));

    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    const pending = await screen.findByRole("button", { name: /calculating/i });
    expect(pending).toBeDisabled();

    release({ data: { total: 1, breakdown: {} } });
    await waitFor(() => expect(screen.getByRole("button", { name: /^calculate$/i })).toBeEnabled());
  });
});

describe("region selector", () => {
  it("lists the regions the backend offers", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    const select = await screen.findByLabelText(/grid region/i);
    await waitFor(() => expect(select.options).toHaveLength(FACTORS.regions.length));
    expect([...select.options].map((o) => o.textContent)).toEqual([
      "France",
      "India",
      "World average",
    ]);
  });

  it("defaults to the backend's default region", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    const select = await screen.findByLabelText(/grid region/i);
    await waitFor(() => expect(select.value).toBe("world"));
  });

  it("shows the per-unit electricity factor for the selected region", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    const select = await screen.findByLabelText(/grid region/i);
    await waitFor(() => expect(select.value).toBe("world"));
    // Factors come from the API, not hardcoded, so the label must track it.
    await waitFor(() => expect(screen.getByText("0.475 kg CO₂e per kWh")).toBeTruthy());
  });

  it("updates the electricity factor when the region changes", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    const select = await screen.findByLabelText(/grid region/i);
    await waitFor(() => expect(select.value).toBe("world"));

    setValue(select, "in");
    await waitFor(() => expect(screen.getByText("0.713 kg CO₂e per kWh")).toBeTruthy());
  });
});