import axios, { AxiosError } from "axios";
import type { AxiosInstance, InternalAxiosRequestConfig } from "axios";
import { API_BASE_URL } from "./config";
import type { ApiErrorBody, MeResponse } from "./types";

/** Marks a request the session-expiry handler should ignore. */
interface FlaggedConfig extends InternalAxiosRequestConfig {
  skipSessionExpiry?: boolean;
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
  // The access and refresh tokens live in httpOnly cookies, so the browser
  // must attach them itself. No token is ever read from or written to
  // localStorage, which means page scripts cannot exfiltrate one.
  withCredentials: true,
});

// Lets App.jsx react to a session that expired mid-visit. Without this the UI
// used to sit on the dashboard firing doomed requests until a manual reload.
let onSessionExpired: (message: string) => void = () => {};
export function setSessionExpiredHandler(
  handler: ((message: string) => void) | null
): void {
  onSessionExpired = handler ?? (() => {});
}

let refreshPromise: Promise<unknown> | null = null;

/**
 * Trade the refresh cookie for a fresh access cookie.
 *
 * Concurrent 401s share one in-flight refresh so a dashboard that fires three
 * requests at once does not trigger three refresh rounds.
 */
async function refreshAccessToken(): Promise<unknown> {
  if (!refreshPromise) {
    refreshPromise = api
      .post("/auth/refresh", null, { skipSessionExpiry: true })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

/**
 * Probe whether a session exists.
 *
 * Flagged skipSessionExpiry because a 401 here is the normal "not logged in
 * yet" answer on first load, not an expiring session. Without the flag the app
 * greets a brand-new visitor with a session-expired banner.
 */
export async function fetchSession(): Promise<MeResponse> {
  const res = await api.get<MeResponse>("/auth/me", { skipSessionExpiry: true });
  return res.data;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorBody>) => {
    const status = error.response?.status;
    const config = (error.config ?? {}) as FlaggedConfig;
    const url = config.url ?? "";
    const isAuthEntry = ["/auth/login", "/auth/register", "/auth/refresh"].some((path) =>
      url.startsWith(path)
    );

    // 401 here means the access cookie expired but the refresh cookie may
    // still be good, so try once before dropping the session.
    //
    // The retried request re-enters this interceptor. If the server keeps
    // answering 401 after a *successful* refresh (revoked session, deleted
    // user, clock skew), an unguarded retry recurses until the tab runs out of
    // memory. _retried marks the replay so only one attempt happens.
    if (status === 401 && !isAuthEntry && !config._retried) {
      try {
        await refreshAccessToken();
        // Only the request's own fields are carried over. Spreading the whole
        // config would replay axios's bookkeeping: `data` may already be a
        // serialised string, `headers` is an AxiosHeaders instance whose methods
        // a plain spread drops, and transformRequest would run a second time.
        return api.request({
          url: config.url,
          method: config.method,
          data: config.data,
          params: config.params,
          headers: config.headers,
          _retried: true,
        });
      } catch {
        // Refresh failed or was rejected; fall through to a clean logout.
      }
    }

    // 422 = no session cookie at all.
    if ((status === 401 || status === 422) && !isAuthEntry && !config.skipSessionExpiry) {
      onSessionExpired(error.response?.data?.msg ?? "Your session has ended.");
    }
    return Promise.reject(error);
  }
);

/** Pull a human-readable message out of an axios error. */
export function errorMessage(
  error: unknown,
  fallback = "Something went wrong."
): string {
  const axiosError = error as AxiosError<ApiErrorBody>;
  const status = axiosError.response?.status;
  if (status === 429) {
    return axiosError.response?.data?.msg ?? "Too many requests. Please wait a moment.";
  }
  if (axiosError.response) {
    const data = axiosError.response.data;
    if (typeof data === "string") return data;
    return data?.msg ?? fallback;
  }
  if (axiosError.request) {
    return "Cannot reach the server. Is the backend running?";
  }
  return axiosError.message || fallback;
}