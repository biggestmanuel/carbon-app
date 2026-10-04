/**
 * FootprintForm validation and submission.
 *
 * The pure input parsing lives in ../lib/footprint and is tested there directly;
 * a DOM test cannot reach it, because type="number" inputs reject the very
 * values parseField exists to catch. What is left here is the wiring: does the
 * form actually send the payload the pure functions produce?
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { apiMock, makeFactorsCatalogue, resetApiMocks } from "../test/api-mock";

// Mock only the transport so no real request is attempted and the payload can be
// inspected directly. errorMessage is the real implementation, so the
// component's user-facing messages are genuinely under test.
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: apiMock };
});

import FootprintForm from "./FootprintForm";

// The US has its own measured car figure; every other region shares the global
// default. That makes the travel-region control meaningful for exactly one
// choice, which is what the form should offer.
const FACTORS = makeFactorsCatalogue({
  defaultRegion: "world",
  carFactors: { us: 0.2485 },
});

/** Force a value React will accept, including values type=number rejects. */
function setValue(element: Element, value: string | number) {
  const proto =
    element.tagName === "SELECT"
      ? window.HTMLSelectElement.prototype
      : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(element, String(value));
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

const byId = (id: string) => document.getElementById(id) as HTMLInputElement;
const selectById = (id: string) => document.getElementById(id) as HTMLSelectElement;

beforeEach(() => {
  resetApiMocks();
  apiMock.get.mockResolvedValue({ data: FACTORS });
  apiMock.post.mockResolvedValue({
    data: {
      id: 9,
      total: 146,
      breakdown: { car: 21, electricity: 95, meat: 15, plant: 10 },
      inputs: {},
      region: "world",
      factors_version: 2,
      factors_applied: { car_km: 0.21, electricity_kwh: 0.475, meat_meal: 5, plant_meal: 2 },
      created_at: "2026-03-01T10:00:00+00:00",
    },
  });
});

describe("blank and invalid input", () => {
  it("sends zeros when every field is left blank", async () => {
    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
    expect(apiMock.post.mock.calls[0]?.[1]).toEqual({
      region: "world",
      car_km: 0,
      electricity_kwh: 0,
      meat_meals: 0,
      plant_meals: 0,
    });
    // The payload must be JSON-safe: no NaN, no null, no undefined.
    for (const value of Object.values(apiMock.post.mock.calls[0]?.[1] as object)) {
      expect(value === undefined || value === null || Number.isNaN(value)).toBe(false);
    }
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses a negative value without calling the API", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    setValue(byId("fp-carKm"), "-5");
    // Submit directly rather than clicking: the input carries min="0", so the
    // browser's own constraint validation blocks a click before React runs.
    // This exercises our guard specifically.
    fireEvent.submit(screen.getByRole("button", { name: /^calculate$/i }).closest("form")!);

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot be negative/i);
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("is also blocked by the browser's own min constraint", async () => {
    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    setValue(byId("fp-carKm"), "-5");
    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    // min="0" means a click never even reaches the submit handler.
    await waitFor(() => expect(screen.getByLabelText(/car km/i)).toBeInvalid());
    expect(apiMock.post).not.toHaveBeenCalled();
  });
});

describe("successful submission", () => {
  it("sends the entered numbers with the selected region", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<FootprintForm onSaved={onSaved} />);

    // Wait for the region catalogue before selecting.
    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());

    setValue(byId("fp-carKm"), "100");
    setValue(byId("fp-electricity"), "200");
    setValue(byId("fp-meatMeals"), "3");
    setValue(byId("fp-plantMeals"), "5");
    setValue(selectById("fp-region"), "fr");

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
    expect(apiMock.post.mock.calls[0]?.[0]).toBe("/footprint/calculate");
    expect(apiMock.post.mock.calls[0]?.[1]).toEqual({
      region: "fr",
      car_km: 100,
      electricity_kwh: 200,
      meat_meals: 3,
      plant_meals: 5,
    });
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ total: 146 }));
  });

  it("offers only travel regions whose car factor actually differs", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    // The US has its own measured car figure; every other region shares the
    // global default, so offering them would put an inert control on screen.
    // That was the original bug.
    await screen.findByLabelText(/grid region/i);
    const select = document.getElementById("fp-travel-region") as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect([...select.options].map((o) => o.value)).toEqual(["", "us"]);
  });

  it("sends a travel region that changes the car factor", async () => {
    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());
    setValue(byId("fp-carKm"), "100");
    setValue(selectById("fp-travel-region"), "us");
    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
    expect(apiMock.post.mock.calls[0]?.[1]).toMatchObject({
      region: "world",
      travel_region: "us",
      car_km: 100,
    });
  });

  it("omits travel_region when it matches home", async () => {
    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
    // Sending an empty string would make the backend look up a region named "".
    expect(apiMock.post.mock.calls[0]?.[1]).not.toHaveProperty("travel_region");
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

  it("warns when the entry was scored with a superseded factor set", async () => {
    // History is only reproducible because the factors used are stored with it.
    // If the current table has moved on, say so rather than silently mixing.
    apiMock.post.mockResolvedValue({
      data: {
        id: 9,
        total: 10,
        breakdown: { car: 0, electricity: 10, meat: 0, plant: 0 },
        inputs: {},
        region: "world",
        factors_version: 1,
        factors_applied: { car_km: 0.21, electricity_kwh: 0.475, meat_meal: 5, plant_meal: 2 },
        created_at: null,
      },
    });

    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    expect(await screen.findByText(/factor set v1/i)).toBeTruthy();
  });

  it("clears the inputs after saving", async () => {
    const user = userEvent.setup();
    render(<FootprintForm onSaved={vi.fn()} />);

    setValue(byId("fp-carKm"), "100");
    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() => expect(byId("fp-carKm").value).toBe(""));
  });

  it("reports a server-side validation error", async () => {
    apiMock.post.mockRejectedValue({
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
    apiMock.post.mockRejectedValue({ request: {} });

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
    let release!: (value: unknown) => void;
    apiMock.post.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        })
    );

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
  /** The label's <select>, typed: findByLabelText only knows it as an HTMLElement. */
  const regionSelect = async () =>
    (await screen.findByLabelText(/grid region/i)) as HTMLSelectElement;

  it("lists the regions the backend offers", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    const select = await regionSelect();
    await waitFor(() => expect(select.options).toHaveLength(FACTORS.regions.length));
    expect([...select.options].map((o) => o.value)).toEqual(
      FACTORS.regions.map((r) => r.code)
    );
  });

  it("defaults to the backend's default region", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    expect((await regionSelect()).value).toBe("world");
  });

  it("shows the per-unit electricity factor for the selected region", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    await waitFor(() => expect((screen.getByLabelText(/grid region/i) as HTMLSelectElement).value).toBe("world"));
    // Factors come from the API, not hardcoded, so the label must track it.
    await waitFor(() => expect(screen.getByText("0.475 kg CO₂e per kWh")).toBeTruthy());
  });

  it("updates the electricity factor when the region changes", async () => {
    render(<FootprintForm onSaved={vi.fn()} />);

    const select = await regionSelect();
    await waitFor(() => expect(select.value).toBe("world"));

    setValue(select, "in");
    await waitFor(() => expect(screen.getByText("0.713 kg CO₂e per kWh")).toBeTruthy());
  });

  it("stays usable when the factor catalogue fails to load", async () => {
    // Regression: the component read catalogue.regions.find unconditionally,
    // so a failed fetch took the whole form down with it.
    apiMock.get.mockRejectedValue({ request: {} });
    const user = userEvent.setup();

    render(<FootprintForm onSaved={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: /^calculate$/i }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledTimes(1));
    expect(apiMock.post.mock.calls[0]?.[1]).toMatchObject({ region: "world" });
  });
});
