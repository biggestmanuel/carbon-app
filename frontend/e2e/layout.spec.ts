/**
 * Layout, verified in a real browser.
 *
 * The Vitest suite asserts `overflow-x`, `white-space` and
 * `font-variant-numeric` by reading styles.css. That catches a rule being
 * deleted; it cannot catch a rule being overridden by a later one, and jsdom
 * resolves none of these properties at all, so it cannot tell a rendered
 * layout apart from a broken one.
 *
 * These tests close that gap. Each one asserts the *computed* value or the real
 * box geometry, at the widths where the layout is under most pressure.
 */
import {
  MFA_SETUP,
  MFA_SETUP_PATTERN,
  MFA_STATUS_PATTERN,
  computed,
  expect,
  horizontalOverflow,
  lineHeight,
  scrollsHorizontally,
  stubApi,
  stubSignedOut,
  test,
  wrappedLines,
} from "./fixtures";

/** The widths worth testing: a small phone, a tablet, a laptop. */
const WIDTHS = [
  { name: "phone", width: 320, height: 720 },
  { name: "tablet", width: 768, height: 900 },
  { name: "laptop", width: 1440, height: 900 },
];

test.describe("the dashboard at narrow widths", () => {
  for (const { name, width, height } of WIDTHS) {
    test(`nothing overflows the viewport at ${name} width`, async ({ dashboard }) => {
      await dashboard.setViewportSize({ width, height });

      const offenders = await horizontalOverflow(dashboard);
      expect(
        offenders,
        `these overflow the ${width}px viewport: ${offenders.join("; ")}`
      ).toEqual([]);
    });
  }
});

test.describe("the history table stays inside its card", () => {
  test("the scroller is contained by the card at phone width", async ({ dashboard }) => {
    await dashboard.setViewportSize({ width: 320, height: 720 });

    const bounds = await dashboard.evaluate(() => {
      const box = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) throw new Error(`no element matched ${selector}`);
        return element.getBoundingClientRect();
      };
      return {
        card: box(".card"),
        scroller: box(".table-scroll"),
        viewport: document.documentElement.clientWidth,
      };
    });

    // The bug this file exists to prevent: the table painting past the card's
    // border instead of the wrapper scrolling.
    expect(bounds.scroller.right).toBeLessThanOrEqual(bounds.card.right + 1);
    expect(bounds.scroller.left).toBeGreaterThanOrEqual(bounds.card.left - 1);
    expect(bounds.scroller.right).toBeLessThanOrEqual(bounds.viewport + 1);
  });

  test("a table too wide for the screen scrolls instead of spilling", async ({ dashboard }) => {
    await dashboard.setViewportSize({ width: 320, height: 720 });

    // Seven nowrap columns at 320px genuinely do not fit, so scrolling here is
    // correct behaviour rather than a defect.
    expect(await scrollsHorizontally(dashboard, ".table-scroll")).toBe(true);
    expect(await computed(dashboard, ".table-scroll", "overflow-x")).toBe("auto");
  });

  test("and it does not scroll when there is room", async ({ dashboard }) => {
    await dashboard.setViewportSize({ width: 1440, height: 900 });

    // A permanent scroller that never scrolls still costs a scrollbar and hides
    // the fact that the table fits.
    expect(await scrollsHorizontally(dashboard, ".table-scroll")).toBe(false);
  });

  test("the table fills the scroller when it fits", async ({ dashboard }) => {
    await dashboard.setViewportSize({ width: 1440, height: 900 });

    const measured = await dashboard.evaluate(() => {
      const table = document.querySelector<HTMLElement>(".table-scroll table");
      const wrapper = document.querySelector<HTMLElement>(".table-scroll");
      if (!table || !wrapper) throw new Error("the history table is missing");
      const style = getComputedStyle(wrapper);
      // clientWidth includes padding, and .table-scroll pads 0.25rem each side so
      // the scroller can sit flush against the card's inner edge. The table is
      // width:100% of the *content* box, not of the padding box.
      const contentWidth =
        wrapper.clientWidth -
        Number.parseFloat(style.paddingLeft) -
        Number.parseFloat(style.paddingRight);
      return {
        table: Math.round(table.getBoundingClientRect().width),
        content: Math.round(contentWidth),
      };
    });

    expect(
      Math.abs(measured.table - measured.content),
      `table ${measured.table}px in a ${measured.content}px content box`
    ).toBeLessThanOrEqual(1);
  });
});

test.describe("cells do not wrap", () => {
  for (const { name, width, height } of WIDTHS) {
    test(`every cell stays on one line at ${name} width`, async ({ dashboard }) => {
      await dashboard.setViewportSize({ width, height });

      expect(await computed(dashboard, "td", "white-space")).toBe("nowrap");
      expect(await computed(dashboard, "th", "white-space")).toBe("nowrap");

      // Wrapping produced two-line rows of uneven height with the date cell
      // becoming the widest column, so the line count is the real assertion.
      // `line-height` has to be numeric for that to be measurable, and the
      // inherited 1.5 unitless value from body is what makes it so.
      const cellLineHeight = await lineHeight(dashboard, "td");
      expect(Number.parseFloat(cellLineHeight)).toBeGreaterThan(0);

      const body = await wrappedLines(dashboard, "tbody td");
      expect(body.length).toBeGreaterThan(0);
      for (const lines of body) {
        expect(lines, `a cell wrapped onto ${lines} lines`).toBeLessThanOrEqual(1);
      }
      for (const lines of await wrappedLines(dashboard, "thead th")) {
        expect(lines, `a heading wrapped onto ${lines} lines`).toBeLessThanOrEqual(1);
      }
    });
  }

  test("body rows are all the same height", async ({ dashboard }) => {
    await dashboard.setViewportSize({ width: 320, height: 720 });

    const heights = await dashboard.evaluate(() =>
      Array.from(document.querySelectorAll<HTMLElement>("tbody tr")).map((row) =>
        row.getBoundingClientRect().height
      )
    );

    expect(heights.length).toBeGreaterThan(1);
    // border-collapse: collapse shares one 1px border between adjacent rows and
    // hands it to one of them, so rows legitimately differ by a pixel. Anything
    // more than that is wrapping, which is what this is checking for.
    const spread = Math.max(...heights) - Math.min(...heights);
    expect(spread, `row heights were ${heights.join(", ")}`).toBeLessThanOrEqual(1);
  });
});

test.describe("digits line up", () => {
  test("the date column uses tabular numerals", async ({ dashboard }) => {
    await dashboard.setViewportSize({ width: 320, height: 720 });

    // Proportional digits change width between rows, so the date column jitters
    // as entries are added.
    expect(await computed(dashboard, "td.date", "font-variant-numeric")).toBe("tabular-nums");
  });

  test("and the dates in the column are the same width", async ({ dashboard }) => {
    await dashboard.setViewportSize({ width: 1440, height: 900 });

    const widths = await dashboard.evaluate(() =>
      Array.from(document.querySelectorAll<HTMLElement>("td.date")).map(
        (cell) => Math.round(cell.getBoundingClientRect().width)
      )
    );

    expect(widths.length).toBeGreaterThan(0);
    expect(new Set(widths).size).toBe(1);
  });
});

test.describe("other pages", () => {
  test("the sign-in page has no horizontal overflow at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 720 });
    // Stubbed as signed out rather than allowed to fail a real connection: a
    // request to localhost:5000 might succeed on a developer machine, which
    // would silently render the dashboard instead.
    await stubSignedOut(page);
    await page.goto("/");
    await expect(page.getByRole("button", { name: /log in/i })).toBeVisible();

    const offenders = await horizontalOverflow(page);
    expect(offenders, `these overflow: ${offenders.join("; ")}`).toEqual([]);
  });

  test("the settings panel and the second-factor panel do not overflow", async ({
    page,
  }) => {
    // The 2FA panel is the widest new content in the app: a 32-character seed and
    // a 16-character recovery code per line, at 320px.
    await page.setViewportSize({ width: 320, height: 720 });
    await stubApi(page);
    await page.goto("/");
    await expect(page.getByRole("table")).toBeVisible();

    // Registered after stubApi, so it wins: Playwright runs the last matching
    // route. Without this the catch-all would abort the settings panel's own
    // calls and the 2FA panel would never render.
    await page.route(MFA_SETUP_PATTERN, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MFA_SETUP),
      })
    );
    // Without this the status call is aborted by the catch-all, and the panel
    // stays on "checking whether two-factor authentication is on" forever, so the
    // button this test needs would never appear.
    await page.route(MFA_STATUS_PATTERN, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ totp_enabled: false, recovery_codes_remaining: 0, changed_at: null }),
      })
    );

    await page.getByRole("button", { name: /^settings$/i }).click();
    await page.getByRole("button", { name: /set up two-factor/i }).click();

    const secret = page.locator(".totp-secret code");
    await expect(secret).toBeVisible();

    const offenders = await horizontalOverflow(page);
    expect(offenders, `these overflow: ${offenders.join("; ")}`).toEqual([]);

    // A seed broken across two lines gets read back as two halves and typed
    // wrong, which locks someone out of their own account.
    expect(await secret.evaluate((node) => getComputedStyle(node).whiteSpace)).toBe(
      "nowrap"
    );
  });

  test("the longest button label fits at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 720 });
    await stubSignedOut(page);
    await page.goto("/");
    await expect(page.getByRole("button", { name: /log in/i })).toBeVisible();

    // A button whose text wraps to two lines is a common narrow-viewport fault
    // and is invisible to a DOM-level assertion.
    const clipped = await page.evaluate(() => {
      const problems: string[] = [];
      for (const button of Array.from(document.querySelectorAll("button"))) {
        const range = document.createRange();
        range.selectNodeContents(button);
        const lines = Array.from(range.getClientRects()).filter((r) => r.height > 0).length;
        if (lines > 1) problems.push(`${button.textContent?.trim()} wraps to ${lines} lines`);
      }
      return problems;
    });
    expect(clipped, clipped.join("; ")).toEqual([]);
  });
});