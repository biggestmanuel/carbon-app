/**
 * A typed stand-in for the api module.
 *
 * vi.mock replaces `api` with a bare object, which TypeScript cannot see through
 * to know that `api.get` is a mock. Importing the mocks from here instead of
 * from "./api" keeps `.mockResolvedValue` and friends type-checked.
 */
import { vi } from "vitest";
import type { Mock } from "vitest";
import type { MeResponse } from "../types";

export type ApiMock = {
  get: Mock;
  post: Mock;
  delete: Mock;
  put: Mock;
  patch: Mock;
};

export const apiMock: ApiMock = {
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
};

export const fetchSessionMock: Mock = vi.fn();
export const setSessionExpiredHandlerMock: Mock = vi.fn();

/** Resolve every call with `data`, so a child component never crashes on undefined. */
export function resolveAllWith(data: unknown = {}) {
  const resolved = () => Promise.resolve({ data });
  for (const method of Object.values(apiMock)) {
    method.mockReset();
    method.mockImplementation(resolved);
  }
}

export function resetApiMocks(): void {
  for (const method of Object.values(apiMock)) method.mockReset();
  fetchSessionMock.mockReset();
}

/** Calls made to one URL, in order. Keeps assertions readable. */
export function callsTo(url: string): unknown[][] {
  return apiMock.get.mock.calls.filter((call) => call[0] === url) as unknown[][];
}

export const ALICE: MeResponse = {
  id: 1,
  username: "alice",
  has_email: true,
  email_verified: false,
  email: "a***e@example.com",
};
