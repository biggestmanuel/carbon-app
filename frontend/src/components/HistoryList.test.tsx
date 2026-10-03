/**
 * The history table used to spill outside its card: it has a minimum content
 * width, and inside the two-column dashboard grid the card was only ~470px wide,
 * so the columns overflowed by up to 111px at narrow viewports.
 *
 * These tests pin the two properties that fix it: the table is wrapped in a
 * scroll container, and the wrapper never extends past the card's border.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { apiMock, resetApiMocks } from "../test/api-mock";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: apiMock };
});

import Dashboard from "./Dashboard";
import HistoryList from "./HistoryList";
// jsdom does not implement overflow-x, white-space or font-variant-numeric, so
// computed styles cannot prove these rules exist. Reading the stylesheet source
// can.
import stylesheet from "../styles.css?raw";

/**
 * Does the stylesheet declare `decl` inside any block for `selector`?
 *
 * Scans every matching block, not just the first: "th, td" appears more than
 * once and the rule under test may be in any of them.
 */
function hasRule(selector: string, decl: string): boolean {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, "g");
  let match: RegExpExecArray | null;
  while ((match = re.exec(stylesheet)) !== null) {
    if (match[1]?.includes(decl)) return true;
  }
  return false;
}

const FACTORS = {
  default_region: "world",
  factors_version: 2,
  source: "static-reference",
  regions: [{ code: "gb", label: "United Kingdom", electricity_kwh: 0.207 }],
  units: {},
};

const ENTRIES = Array.from({ length: 6 }, (_, i) => ({
  id: 6 - i,
  car_km: 100 + i,
  electricity_kwh: 200,
  meat_meals: 3,
  plant_meals: 5,
  total: 134.865 + i,
  region: "gb",
  factors_version: 2,
  factors_applied: null,
  created_at: `2026-03-0${i + 1}T10:35:00+00:00`,
}));

const table = () => screen.getByRole("table");

beforeEach(() => {
  resetApiMocks();
  apiMock.get.mockImplementation((url: string) => {
    if (url === "/footprint/factors") return Promise.resolve({ data: FACTORS });
    if (url === "/footprint/history")
      return Promise.resolve({
        data: { entries: ENTRIES, total_entries: 6, limit: 25, offset: 0 },
      });
    if (url === "/footprint/summary")
      return Promise.resolve({
        data: {
          entries: 6,
          total: 800,
          average: 133,
          breakdown: {},
          by_category: {},
          regions: ["gb"],
          factors_versions: [2],
        },
      });
    return Promise.resolve({ data: { sessions: [] } });
  });
});

describe("HistoryList layout", () => {
  it("wraps the table in a horizontally scrollable container", async () => {
    render(<HistoryList refreshKey={0} />);
    await waitFor(() => expect(table()).toBeTruthy());

    const wrapper = table().closest(".table-scroll");
    expect(wrapper).toBeTruthy();
    // Without this rule the table paints outside the card on narrow viewports.
    expect(hasRule(".table-scroll", "overflow-x: auto")).toBe(true);
  });

  it("spans the full width instead of sitting in a narrow grid column", async () => {
    render(
      <Dashboard
        username="alice"
        account={{ id: 1, username: "alice", has_email: false, email_verified: false }}
        onLogout={vi.fn()}
        onAccountDeleted={vi.fn()}
        onAccountChanged={vi.fn()}
      />
    );
    await waitFor(() => expect(table()).toBeTruthy());

    // History must be a sibling of the two-column grid, not inside it.
    const grid = document.querySelector(".columns");
    expect(grid?.contains(table())).toBe(false);
    expect(table().closest(".dashboard")).toBeTruthy();
  });

  it("gives every cell a nowrap rule so rows stay one line", async () => {
    render(<HistoryList refreshKey={0} />);
    await waitFor(() => expect(table()).toBeTruthy());

    expect(hasRule("th, td", "white-space: nowrap")).toBe(true);
  });

  it("uses tabular figures for the date column", async () => {
    render(<HistoryList refreshKey={0} />);
    await waitFor(() => expect(table()).toBeTruthy());

    // The class is on the cell; the rule itself is asserted here.
    expect(table().querySelector("td.date")).toBeTruthy();
    expect(hasRule("td.date", "font-variant-numeric: tabular-nums")).toBe(true);
  });

  it("does not force a minimum table width that would overflow", async () => {
    // An earlier attempt added min-width: 30rem, which made the table scroll
    // even at full desktop width. Containment must come from the wrapper only.
    expect(hasRule("table", "min-width")).toBe(false);
  });
});

describe("HistoryList content", () => {
  it("shortens region codes for display", async () => {
    render(<HistoryList refreshKey={0} />);
    await waitFor(() => expect(table()).toBeTruthy());

    // "gb" would be cryptic; the full name is available on hover.
    const cell = table().querySelector("tbody tr td:nth-child(2)");
    expect(cell?.textContent).toBe("UK");
    expect(cell?.getAttribute("title")).toBe("gb");
  });

  it("rounds the displayed total but keeps it readable", async () => {
    render(<HistoryList refreshKey={0} />);
    await waitFor(() => expect(table()).toBeTruthy());

    // 134.865 was showing in full, which was both noisy and the widest cell.
    const totals = [...table().querySelectorAll("tbody td:last-child")];
    expect(totals[0]?.textContent).toBe("134.87");
    expect(totals.every((td) => (td.textContent ?? "").length <= 6)).toBe(true);
  });

  it("drops seconds from the date", async () => {
    render(<HistoryList refreshKey={0} />);
    await waitFor(() => expect(table()).toBeTruthy());

    // A fixed locale keeps the column width stable between rows.
    expect(table().querySelector("td.date")?.textContent).not.toMatch(/:\d{2}:\d{2}/);
  });

  it("labels headers for assistive technology", async () => {
    render(<HistoryList refreshKey={0} />);
    await waitFor(() => expect(table()).toBeTruthy());

    const headers = [...table().querySelectorAll("th")];
    expect(headers.length).toBe(7);
    expect(headers.every((th) => th.getAttribute("scope") === "col")).toBe(true);
    // A caption gives the table a name without showing anything.
    expect(table().querySelector("caption")).toBeTruthy();
  });

  it("keeps the previous rows visible while a refresh is in flight", async () => {
    // Regression risk from the loading-state fix: flashing an empty table on
    // every new entry would be worse than a brief spinner.
    const { rerender } = render(<HistoryList refreshKey={0} />);
    await waitFor(() => expect(table()).toBeTruthy());

    apiMock.get.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({ data: { entries: ENTRIES, total_entries: 6 } }), 50))
    );
    rerender(<HistoryList refreshKey={1} />);

    expect(table()).toBeTruthy();
    expect(screen.queryByText(/loading history/i)).toBeNull();
  });
});
