/**
 * Dashboard aggregation panels. The gap these close: entries were written to the
 * database with no way to read them back, so these components had nothing to
 * render. They also assert the totals stay correct when a user's history mixes
 * regions.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { apiMock, resetApiMocks } from "../test/api-mock";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: apiMock };
});

import Dashboard from "./Dashboard";
import type { MeResponse } from "../types";

const ACCOUNT: MeResponse = {
  id: 1,
  username: "alice",
  has_email: true,
  email_verified: true,
};

const FACTORS = {
  default_region: "world",
  factors_version: 2,
  source: "static-reference",
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
    factors_version: 2,
    factors_applied: null,
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
    factors_version: 2,
    factors_applied: null,
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

/** A Dashboard with no-op callbacks, so each test only states what it cares about. */
function renderDashboard(overrides: Partial<React.ComponentProps<typeof Dashboard>> = {}) {
  const props: React.ComponentProps<typeof Dashboard> = {
    username: "alice",
    account: ACCOUNT,
    onLogout: vi.fn(),
    onAccountDeleted: vi.fn(),
    onAccountChanged: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<Dashboard {...props} />) };
}

type RouteMap = Record<string, () => Promise<unknown>>;

/** Resolve GETs from an override map, falling back to the happy-path payloads. */
function useRoutes(overrides: RouteMap = {}) {
  apiMock.get.mockImplementation((url: string) => {
    const override = overrides[url];
    if (override) return override();
    if (url === "/footprint/factors") return Promise.resolve({ data: FACTORS });
    if (url === "/footprint/history")
      return Promise.resolve({ data: { entries: ENTRIES, total_entries: 2, limit: 25, offset: 0 } });
    if (url === "/footprint/summary") return Promise.resolve({ data: SUMMARY });
    // /account/sessions and anything else: an empty but well-formed payload.
    return Promise.resolve({ data: { sessions: [] } });
  });
}

const ok = (data: unknown) => () => Promise.resolve({ data });
const fail = (data: unknown, status = 500) => () => Promise.reject({ response: { status, data } });

beforeEach(() => {
  resetApiMocks();
  useRoutes();
});

describe("Summary", () => {
  it("shows the lifetime total, average and entry count", async () => {
    renderDashboard();

    expect(await screen.findByText("274.8 kg CO₂e")).toBeTruthy();
    expect(screen.getByText(/2 entries/)).toBeTruthy();
    expect(screen.getByText(/average 137.4 kg per entry/)).toBeTruthy();
  });

  it("uses the singular form for one entry", async () => {
    useRoutes({
      "/footprint/summary": ok({ ...SUMMARY, entries: 1, total: 10, average: 10 }),
    });

    renderDashboard();

    await waitFor(() => expect(screen.getByText(/^1 entry\b/)).toBeTruthy());
  });

  it("breaks the total down by category", async () => {
    renderDashboard();

    expect(await screen.findByText("Electricity: 153.8 kg")).toBeTruthy();
    expect(screen.getByText("Car travel: 21 kg")).toBeTruthy();
  });

  it("renders zeros rather than NaN for a partial payload", async () => {
    // Regression: the component read summary.total directly, so an incomplete
    // response rendered "undefined kg CO2e" and entries.length threw.
    useRoutes({ "/footprint/summary": ok({}) });

    renderDashboard();

    expect(await screen.findByText("0 kg CO₂e")).toBeTruthy();
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it("shows an error when the summary request fails", async () => {
    useRoutes({
      "/footprint/summary": fail({ msg: "Could not load summary." }),
    });

    renderDashboard();

    expect(await screen.findByText(/could not load summary/i)).toBeTruthy();
  });
});

describe("HistoryList", () => {
  it("lists every stored entry newest first", async () => {
    renderDashboard();

    await waitFor(() => expect(screen.getByText(/showing 2 of 2/i)).toBeTruthy());
    const rows = screen.getAllByRole("row").slice(1); // drop the header
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("142.6"); // the newer India entry
  });

  it("shows the empty state with no entries", async () => {
    useRoutes({ "/footprint/history": ok({ entries: [], total_entries: 0 }) });

    renderDashboard();

    expect(await screen.findByText(/no entries yet/i)).toBeTruthy();
  });

  it("does not throw when the entries field is missing", async () => {
    // Regression: entries.length threw on a partial payload.
    useRoutes({ "/footprint/history": ok({}) });

    renderDashboard();

    expect(await screen.findByText(/no entries yet/i)).toBeTruthy();
  });

  it("requests a bounded page size", async () => {
    renderDashboard();

    await waitFor(() => expect(screen.getByText(/showing 2 of 2/i)).toBeTruthy());
    const call = apiMock.get.mock.calls.find((c) => c[0] === "/footprint/history");
    expect(call?.[1]).toEqual({ params: { limit: 25 } });
  });
});

describe("Dashboard chrome", () => {
  it("greets the signed-in user and offers logout", async () => {
    const { props } = renderDashboard();

    expect(await screen.findByText(/signed in as alice/i)).toBeTruthy();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /log out/i }));
    expect(props.onLogout).toHaveBeenCalled();
  });

  it("refetches history and summary after a new entry", async () => {
    const user = userEvent.setup();
    apiMock.post.mockResolvedValue({
      data: { total: 1, breakdown: {}, region: "world", factors_version: 2 },
    });

    renderDashboard();
    await waitFor(() => expect(screen.getByText(/showing 2 of 2/i)).toBeTruthy());

    const historyBefore = apiMock.get.mock.calls.filter((c) => c[0] === "/footprint/history").length;
    const summaryBefore = apiMock.get.mock.calls.filter((c) => c[0] === "/footprint/summary").length;

    await user.click(screen.getByRole("button", { name: /^calculate$/i }));

    await waitFor(() =>
      expect(apiMock.get.mock.calls.filter((c) => c[0] === "/footprint/history").length)
        .toBeGreaterThan(historyBefore)
    );
    expect(apiMock.get.mock.calls.filter((c) => c[0] === "/footprint/summary").length)
      .toBeGreaterThan(summaryBefore);
  });

  it("hides the account settings until they are asked for", async () => {
    const user = userEvent.setup();
    renderDashboard();

    expect(screen.queryByText(/delete account/i)).toBeNull();
    await user.click(screen.getByRole("button", { name: /^settings$/i }));
    expect(await screen.findByText(/delete account/i)).toBeTruthy();
  });

  it("nudges an unverified address to be confirmed", async () => {
    renderDashboard({
      account: { ...ACCOUNT, email_verified: false, email: "a***e@example.com" },
    });

    expect(await screen.findByRole("button", { name: /send confirmation link/i })).toBeTruthy();
  });

  it("does not nag about verification once the address is confirmed", async () => {
    renderDashboard();

    await screen.findByText(/signed in as alice/i);
    expect(screen.queryByRole("button", { name: /send confirmation link/i })).toBeNull();
  });
});
