/**
 * Tests for the axios layer: credentialed requests and the transparent
 * refresh. This was the part previously verified only by hand in a browser,
 * so the failure modes worth pinning are:
 *
 *  - a 401 retries once after refreshing, and the caller never sees the 401
 *  - concurrent 401s share one refresh, not one each
 *  - a failed refresh ends the session rather than looping
 *  - the login endpoint's 401 is not mistaken for an expired session
 *  - the first-load probe does not fire the expiry banner
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import MockAdapter from "axios-mock-adapter";

import { api, errorMessage, fetchSession, setSessionExpiredHandler } from "../api";

describe("api client", () => {
  let mock;
  let onSessionExpired;

  beforeEach(() => {
    mock = new MockAdapter(api);
    onSessionExpired = vi.fn();
    setSessionExpiredHandler(onSessionExpired);
  });

  afterEach(() => {
    mock.restore();
    setSessionExpiredHandler(null);
  });

  describe("requests", () => {
    it("sends credentials so the browser attaches the httpOnly cookie", () => {
      expect(api.defaults.withCredentials).toBe(true);
    });

    it("does not attach an Authorization header", async () => {
      let sent;
      mock.onPost("/anything").reply((config) => {
        sent = config.headers;
        return [200, {}];
      });

      await api.post("/anything");

      // The token lives in a cookie; a header would mean we regressed.
      expect(sent.Authorization).toBeUndefined();
    });
  });

  describe("transparent refresh", () => {
    it("retries the request once after a 401 and returns the success", async () => {
      let attempts = 0;
      let refreshed = 0;

      mock.onPost("/footprint/calculate").reply(() => {
        attempts += 1;
        return attempts === 1 ? [401, { msg: "Session expired" }] : [201, { total: 42 }];
      });
      mock.onPost("/auth/refresh").reply(() => {
        refreshed += 1;
        return [200, { msg: "Token refreshed" }];
      });

      const res = await api.post("/footprint/calculate", {});

      expect(res.status).toBe(201);
      expect(res.data.total).toBe(42);
      expect(refreshed).toBe(1);
      expect(attempts).toBe(2);
      // The user never learns their session had lapsed.
      expect(onSessionExpired).not.toHaveBeenCalled();
    });

    it("shares one refresh across concurrent 401s", async () => {
      let refreshCalls = 0;

      mock.onGet("/footprint/summary").reply(() => [401, {}]);
      mock.onGet("/footprint/history").reply(() => [401, {}]);
      mock.onPost("/auth/refresh").reply(() => {
        refreshCalls += 1;
        return [200, {}];
      });

      // The dashboard fires these together on mount.
      await Promise.allSettled([
        api.get("/footprint/summary"),
        api.get("/footprint/history"),
        api.get("/footprint/summary"),
      ]);

      expect(refreshCalls).toBe(1);
    });

    it("does not retry forever when the refresh itself is rejected", async () => {
      let attempts = 0;
      let refreshes = 0;

      mock.onPost("/footprint/calculate").reply(() => {
        attempts += 1;
        return [401, {}];
      });
      mock.onPost("/auth/refresh").reply(() => {
        refreshes += 1;
        return [401, {}];
      });

      await expect(api.post("/footprint/calculate", {})).rejects.toBeTruthy();

      // A rejected refresh means there is no point replaying the request, so
      // it is attempted once. What matters is that the count stays small and
      // the caller gets a rejection either way.
      expect(attempts).toBe(1);
      expect(refreshes).toBe(1);
    });

    it("stops after one replay when the server keeps returning 401", async () => {
      // Regression: refresh succeeds, but the endpoint still answers 401.
      // Without a retry guard this recursed until the tab ran out of memory
      // and the worker died with exit code 134.
      let attempts = 0;
      let refreshes = 0;

      mock.onPost("/footprint/calculate").reply(() => {
        attempts += 1;
        return [401, { msg: "Session expired" }];
      });
      mock.onPost("/auth/refresh").reply(() => {
        refreshes += 1;
        return [200, { msg: "Token refreshed" }];
      });

      await expect(api.post("/footprint/calculate", {})).rejects.toBeTruthy();

      expect(attempts).toBe(2);
      expect(refreshes).toBe(1);
      // The user is not left waiting on a request that will never resolve.
      expect(onSessionExpired).toHaveBeenCalledWith("Session expired");
    });

    it("handles concurrent 401s without leaking or looping", async () => {
      let refreshCalls = 0;

      mock.onGet("/footprint/summary").reply(401, {});
      mock.onGet("/footprint/history").reply(401, {});
      mock.onPost("/auth/refresh").reply(() => {
        refreshCalls += 1;
        return [200, {}];
      });

      const settled = await Promise.allSettled([
        api.get("/footprint/summary"),
        api.get("/footprint/history"),
        api.get("/footprint/summary"),
      ]);

      expect(settled).toHaveLength(3);
      expect(settled.every((s) => s.status === "rejected")).toBe(true);
      expect(refreshCalls).toBe(1);
    });

    it("ends the session when the refresh is rejected", async () => {
      mock.onPost("/footprint/calculate").reply(401, { msg: "Session expired" });
      mock.onPost("/auth/refresh").reply(401, { msg: "Invalid token" });

      await expect(api.post("/footprint/calculate", {})).rejects.toBeTruthy();

      // The message shown is the original request's, not the refresh's: the
      // backend words that one as "Session expired, please log in again",
      // which is what the user actually needs to read. Leaking the raw refresh
      // error ("Invalid token") would be accurate but unhelpful.
      expect(onSessionExpired).toHaveBeenCalledWith("Session expired");
    });

    it("treats a 422 as no session and ends it", async () => {
      mock.onGet("/footprint/history").reply(422, { msg: "Authentication required" });
      mock.onPost("/auth/refresh").reply(401, {});

      await expect(api.get("/footprint/history")).rejects.toBeTruthy();

      expect(onSessionExpired).toHaveBeenCalled();
    });
  });

  describe("endpoints that must not trigger a session expiry", () => {
    it("reports a wrong password without claiming the session ended", async () => {
      mock.onPost("/auth/login").reply(401, { msg: "Bad credentials" });

      await expect(
        api.post("/auth/login", { username: "a", password: "b" })
      ).rejects.toBeTruthy();

      // This is the bug that greeted a failed login with an expiry banner.
      expect(onSessionExpired).not.toHaveBeenCalled();
    });

    it("keeps the session on a duplicate-username conflict", async () => {
      mock.onPost("/auth/register").reply(409, { msg: "Username already taken" });

      await expect(api.post("/auth/register", {})).rejects.toBeTruthy();

      expect(onSessionExpired).not.toHaveBeenCalled();
    });
  });

  describe("fetchSession", () => {
    it("does not fire the expiry handler when there is no session", async () => {
      mock.onGet("/auth/me").reply(401, { msg: "Authentication required" });

      await expect(fetchSession()).rejects.toBeTruthy();

      // A brand new visitor must not be told their session expired.
      expect(onSessionExpired).not.toHaveBeenCalled();
    });

    it("returns the user when a session exists", async () => {
      mock.onGet("/auth/me").reply(200, { id: 1, username: "alice" });

      await expect(fetchSession()).resolves.toEqual({ id: 1, username: "alice" });
      expect(onSessionExpired).not.toHaveBeenCalled();
    });
  });

  describe("errorMessage", () => {
    it("surfaces the 429 body", () => {
      const err = { response: { status: 429, data: { msg: "Too many requests." } } };
      expect(errorMessage(err)).toBe("Too many requests.");
    });

    it("explains an unreachable server", () => {
      expect(errorMessage({ request: {} })).toMatch(/backend running/i);
    });

    it("falls back for an empty response body", () => {
      expect(errorMessage({ response: { status: 500, data: {} } }, "Boom")).toBe("Boom");
    });

    it("handles a non-JSON body", () => {
      expect(errorMessage({ response: { status: 502, data: "<html>" } })).toBe("<html>");
    });
  });
});