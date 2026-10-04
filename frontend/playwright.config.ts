import { defineConfig, devices } from "@playwright/test";

/**
 * Real-browser layout tests.
 *
 * jsdom implements none of overflow-x, white-space or font-variant-numeric, so
 * the Vitest suite asserts those rules by reading the stylesheet source. That
 * catches a rule being deleted but not a rule being overridden by a later one,
 * and it cannot catch a container actually overflowing at a given width. Only a
 * real engine can, which is what this project does.
 *
 * The API is stubbed with page.route, so these run against the built frontend
 * with no backend and no database. That keeps them fast and means a backend
 * outage cannot be mistaken for a layout regression.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? "github" : "list",

  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: {
    // Serving the production build, not the dev server: the dev server injects
    // HMR client code that changes layout timing and adds noise.
    //
    // --host 127.0.0.1 is not redundant with the baseURL. Without it vite binds
    // to `localhost`, which on some machines resolves to ::1 only, and a request
    // to 127.0.0.1 then fails outright. Pinning the host removes that IPv4/IPv6
    // split rather than relying on which one the machine prefers.
    command:
      "npm run build && npm run preview -- --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
