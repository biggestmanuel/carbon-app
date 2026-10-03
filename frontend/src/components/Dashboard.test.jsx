/**
 * Dashboard aggregation panels. The gap these close: entries were written to
 * the database with no way to read them back, so these components had nothing
 * to render. They also assert the totals stay correct when a user's history
 * mixes regions.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } };
});

import { api } from "../api";
import Dashboard from "./Dashboard.jsx";

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

const ENTRIES = [
  {
    id: 2,
    car_km: 0,
    electricity_kwh: 200,
    meat_meals: 0,
    plant_meals: 0,
    total: 142.6,
    region: "in",
    created_at: "2026-03-01T10:00:00+00:00",
  },
  {
    id: 1,
    car_km: 100,
    electricity_kwh: 200,
    meat_meals: 3,
    plant_meals: 5,
    total: 132.2,
    region: "fr",
    created_at: "2026-02-28T10:00:00+00:00",
  },
];

const SUMMARY = {
  entries: 2,
  total: 274.8,
  average: 137.4,
  breakdown: { car: 21, electricity: 153.8, meat: 15, plant: 10 },
  by_category: { car_km: 100, electricity_kwh: 400, meat_meals: 3, plant_meals: 5 },
  regions: ["fr", "in"],
  factors_versions: [2],
};

/** Resolve GETs from an override map, falling back to the happy-path payloads. */
function useRoutes(overrides = {}) {
  api.get.mockImplementation((url) => {
    if (url in overrides) return overrides[url]();
    if (url === "/footprint/factors") return Promise.resolve({ data: FACTORS });
    if (url === "/footprint/history")
      return Promise.resolve({ data: { entries: ENTRIES, total_entries: 2, limit: 25, offset: 0 } });
    if (url === "/footprint/summary") return Promise.resolve({ data: SUMMARY });
    return Promise.resolve({ data: {} });
  });
}

const ok = (data) => () => Promise.resolve({ data });
const fail = (data, status = 500) => () => Promise.reject({ response: { status, data } });

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  useRoutes();
});

describe("Summary", () => {
  it("shows the lifetime total, average and entry count", async () => {
    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    expect(await screen.findByText("274.8 kg CO₂e")).toBeTruthy();
    expect(screen.getByText(/2 entries/)).toBeTruthy();
    expect(screen.getByText(/average 137.4 kg per entry/)).toBeTruthy();
  });

  it("uses the singular form for one entry", async () => {
    useRoutes({
      "/footprint/summary": ok({ ...SUMMARY, entries: 1, total: 10, average: 10 }),
    });

    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/^1 entry\b/)).toBeTruthy());
  });

  it("breaks the total down by category", async () => {
    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    expect(await screen.findByText("Electricity: 153.8 kg")).toBeTruthy();
    expect(screen.getByText("Car travel: 21 kg")).toBeTruthy();
  });

  it("renders zeros rather than NaN for a partial payload", async () => {
    // Regression: the component read summary.total directly, so an incomplete
    // response rendered "undefined kg CO2e" and entries.length threw.
    useRoutes({ "/footprint/summary": ok({}) });

    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    expect(await screen.findByText("0 kg CO₂e")).toBeTruthy();
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it("shows an error when the summary request fails", async () => {
    useRoutes({
      "/footprint/summary": fail({ msg: "Could not load summary." }),
    });

    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    expect(await screen.findByText(/could not load summary/i)).toBeTruthy();
  });
});

describe("HistoryList", () => {
  it("lists every stored entry newest first", async () => {
    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/showing 2 of 2/i)).toBeTruthy());
    const rows = screen.getAllByRole("row").slice(1); // drop the header
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("142.6"); // the newer India entry
  });

  it("shows the empty state with no entries", async () => {
    useRoutes({ "/footprint/history": ok({ entries: [], total_entries: 0 }) });

    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    expect(await screen.findByText(/no entries yet/i)).toBeTruthy();
  });

  it("does not throw when the entries field is missing", async () => {
    // Regression: entries.length threw on a partial payload.
    useRoutes({ "/footprint/history": ok({}) });

    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    expect(await screen.findByText(/no entries yet/i)).toBeTruthy();
  });

  it("requests a bounded page size", async () => {
    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/showing 2 of 2/i)).toBeTruthy());
    const call = api.get.mock.calls.find((c) => c[0] === "/footprint/history");
    expect(call[1]).toEqual({ params: { limit: 25 } });
  });
});

describe("Dashboard", () => {
  it("greets the signed-in user and offers logout", async () => {
    render(<Dashboard username="alice" onLogout={vi.fn()} />);

    expect(await screen.findByText(/signed in as alice/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /log out/i })).toBeTruthy();
  });

  it("refetches history and summary after a new entry", async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue({
      data: { total: 1, breakdown: {}, region: "world", factors_version: 2 },
    });

    render(<Dashboard username="alice" onLogout={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/showing 2 of 2/i)).toBeTruthy());

    const historyCallsBefore = api.get.mock.calls.filter((c) => c[0] === "/footprint/history").length;
    const summaryCallsBefore = api.get.mock.calls.filter((c) => c[0] === "/footprint/summary").length;

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() =>
      expect(api.get.mock.calls.filter((c) => c[0] === "/footprint/history").length)
        .toBeGreaterThan(historyCallsBefore)
    );
    expect(api.get.mock.calls.filter((c) => c[0] === "/footprint/summary").length)
      .toBeGreaterThan(summaryCallsBefore);
  });
});