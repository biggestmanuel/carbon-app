/**
 * Shared fixtures for the browser tests.
 *
 * Every API call is stubbed, so these run against the built frontend with no
 * backend and no database. A backend outage then cannot be mistaken for a
 * layout regression, and the suite stays fast enough to run on every push.
 *
 * Routes are matched on path rather than on origin. The app's API base URL is
 * configurable (`VITE_API_URL`) and its default is localhost, while the preview
 * server here is 127.0.0.1 -- globbing on the path means these stubs keep
 * working whichever host the frontend is pointed at.
 */
import { expect, test as base } from "@playwright/test";
import type { Page } from "@playwright/test";

const USER = {
  id: 1,
  username: "alice",
  has_email: true,
  email_verified: true,
  email: "a***e@example.com",
};

/**
 * Deliberately awkward values: large numbers, a long region code and a
 * zero-total row. These are what break a table layout, so they are what the
 * fixtures should contain.
 */
export const ENTRIES = [
  {
    id: 6, car_km: 12345.6, electricity_kwh: 9876.5, meat_meals: 120, plant_meals: 340,
    total: 9876.5432, region: "gb", factors_version: 3, factors_applied: null,
    created_at: "2026-03-06T23:59:59+00:00",
  },
  {
    id: 5, car_km: 1, electricity_kwh: 1, meat_meals: 0, plant_meals: 0,
    total: 0.5, region: "world", factors_version: 3, factors_applied: null,
    created_at: "2026-03-05T00:00:00+00:00",
  },
];

export const FACTORS = {
  default_region: "world",
  factors_version: 3,
  source: "static-reference",
  regions: [
    { code: "world", label: "World average", electricity_kwh: 0.475, car_km: 0.16984, car_km_is_default: true, provenance: {} },
    { code: "us", label: "United States", electricity_kwh: 0.372, car_km: 0.2485, car_km_is_default: false, provenance: {} },
  ],
  units: {},
};

const SUMMARY = {
  entries: 2,
  total: 9877.0432,
  average: 4938.5216,
  breakdown: { car: 2593.1, electricity: 4947.3, meat: 600, plant: 680 },
  by_category: {},
  regions: ["gb", "world"],
  factors_versions: [3],
};

function json(body: unknown) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

/**
 * Endpoint patterns, as regular expressions rather than globs.
 *
 * A glob matches only when the URL ends with that path, and the app calls the
 * history endpoint with a query string, so the glob fell through to the
 * catch-all and was reported as an unstubbed call. Each pattern below accepts an
 * optional query string or the end of the URL, and nothing else.
 */
const ENDPOINTS = {
  me: /\/auth\/me(\?|$)/,
  factors: /\/footprint\/factors(\?|$)/,
  history: /\/footprint\/history(\?|$)/,
  summary: /\/footprint\/summary(\?|$)/,
  sessions: /\/account\/sessions(\?|$)/,
};

/** Request kinds that belong to the page itself rather than to the API. */
const PAGE_RESOURCE_TYPES = new Set([
  "document",
  "stylesheet",
  "script",
  "image",
  "font",
  "manifest",
  "other",
]);

/**
 * Stub the API and sign the user in.
 *
 * Order matters and the direction is counter-intuitive: the *last* registered
 * route is the one that runs, so the specific stubs are installed after the
 * catch-all. Installing them the other way round lets the catch-all swallow
 * every call before any stub sees it. Verified with a probe rather than
 * assumed, because the documentation is easy to misread here.
 */
export async function stubApi(page: Page) {
  await page.route(/.+/, async (route) => {
    // Everything the browser fetches to draw the page: the document itself, the
    // bundle, fonts. Decided by resource type rather than by origin, because
    // the page's origin is not yet known while routes are being installed and
    // the API base URL is configurable.
    if (PAGE_RESOURCE_TYPES.has(route.request().resourceType())) {
      return route.continue();
    }

    // Anything left is a fetch or XHR to an endpoint these tests did not stub,
    // which means the app made a request nobody accounted for. Failing is the
    // right response: silently allowing it would let a layout test pass against
    // a screen that rendered nothing useful.
    await route.abort();
    throw new Error(`unstubbed API call in a browser test: ${route.request().url()}`);
  });

  await page.route(ENDPOINTS.me, (route) => route.fulfill(json(USER)));
  await page.route(ENDPOINTS.factors, (route) => route.fulfill(json(FACTORS)));
  await page.route(ENDPOINTS.history, (route) =>
    route.fulfill(
      json({
        entries: ENTRIES,
        total_entries: ENTRIES.length,
        limit: 25,
        offset: 0,
      })
    )
  );
  await page.route(ENDPOINTS.summary, (route) => route.fulfill(json(SUMMARY)));
  await page.route(ENDPOINTS.sessions, (route) => route.fulfill(json({ sessions: [] })));
}

export const test = base.extend<{ dashboard: Page }>({
  dashboard: async ({ page }, use) => {
    await stubApi(page);
    await page.goto("/");
    // Wait until the dashboard has actually rendered, so a layout assertion
    // cannot pass against a loading placeholder.
    await expect(page.getByRole("table")).toBeVisible();
    await use(page);
  },
});

/** Exposed so specs can stub the 2FA endpoints the settings panel calls. */
export const MFA_SETUP_PATTERN = /\/auth\/mfa\/start(\?|$)/;
export const MFA_STATUS_PATTERN = /\/auth\/mfa\/status(\?|$)/;

export const MFA_SETUP = {
  secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
  provisioning_uri:
    "otpauth://totp/carbon-app%3Aalice?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP" +
    "&issuer=carbon-app&algorithm=SHA1&digits=6&period=30",
  issuer: "carbon-app",
  digits: 6,
  period: 30,
};

export { expect };

/** The signed-out view: /auth/me says there is no session. */
export async function stubSignedOut(page: Page) {
  await page.route(ENDPOINTS.me, (route) =>
    route.fulfill({ status: 401, contentType: "application/json", body: '{"msg":"no session"}' })
  );
}

/**
 * Elements whose right edge sits past the viewport, ignoring anything inside a
 * horizontal scroll container.
 *
 * Offenders are returned rather than a boolean, so a failure names what broke.
 * Content inside an `overflow-x: auto` container is *supposed* to be wider than
 * the window -- that is what the scroller is for -- so those elements are
 * excluded. The scroller itself is not excluded: if the scroller is what
 * overflows, the layout is broken.
 */
export async function horizontalOverflow(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const limit = document.documentElement.clientWidth;
    const offenders: string[] = [];

    const insideScroller = (element: Element): boolean => {
      for (let node = element.parentElement; node; node = node.parentElement) {
        const overflow = getComputedStyle(node).overflowX;
        if (overflow === "auto" || overflow === "scroll") return true;
      }
      return false;
    };

    const describe = (element: Element) => {
      const classes = String(element.className ?? "").trim().split(/\s+/).filter(Boolean);
      return element.tagName.toLowerCase() + (classes.length ? "." + classes.join(".") : "");
    };

    for (const element of Array.from(document.querySelectorAll("body *"))) {
      const box = element.getBoundingClientRect();
      // Unlaid-out elements have no box and therefore cannot be overflowing.
      if (box.width === 0 || box.height === 0) continue;
      if (box.right <= limit + 1) continue;
      if (insideScroller(element)) continue;
      offenders.push(`${describe(element)} right=${Math.round(box.right)} viewport=${limit}`);
    }
    return offenders;
  });
}

/** Whether an element actually scrolls horizontally, rather than merely could. */
export async function scrollsHorizontally(page: Page, selector: string): Promise<boolean> {
  return page.evaluate((sel) => {
    const element = document.querySelector<HTMLElement>(sel);
    if (!element) throw new Error(`no element matched ${sel}`);
    return element.scrollWidth > element.clientWidth + 1;
  }, selector);
}

/** A computed property value: what the browser actually resolved, not the source. */
export async function computed(
  page: Page,
  selector: string,
  property: string
): Promise<string> {
  return page.evaluate(
    ([sel, prop]) => {
      const element = document.querySelector<HTMLElement>(sel);
      if (!element) throw new Error(`no element matched ${sel}`);
      return getComputedStyle(element).getPropertyValue(prop).trim();
    },
    [selector, property] as const
  );
}

/**
 * How many lines each cell's content occupies.
 *
 * Measured as content height over the computed line height, not from
 * `Range.getClientRects()`: a range reports one rect per inline box, so a cell
 * containing a single `<strong>` reports two rects on one line. Height against a
 * numeric line height is the only version of this that measures wrapping rather
 * than markup.
 */
export async function wrappedLines(page: Page, selector: string): Promise<number[]> {
  return page.evaluate((sel) => {
    return Array.from(document.querySelectorAll<HTMLElement>(sel)).map((cell) => {
      const style = getComputedStyle(cell);
      const lineHeight = Number.parseFloat(style.lineHeight);
      const padding =
        Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
      const contentHeight = cell.clientHeight - padding;
      // "normal" cannot be divided by; the caller asserts it is numeric, so
      // reporting NaN here surfaces that as a failure rather than hiding it.
      if (!Number.isFinite(lineHeight) || lineHeight <= 0) return Number.NaN;
      return Math.round(contentHeight / lineHeight);
    });
  }, selector);
}

/** The computed value of one property on one element. */
export async function lineHeight(page: Page, selector: string): Promise<string> {
  return computed(page, selector, "line-height");
}