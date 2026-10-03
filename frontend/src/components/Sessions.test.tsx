/**
 * Per-device session management.
 *
 * The behaviour worth pinning is that revoking one device leaves the others
 * alone. Losing a phone should not sign you out of your laptop, which is exactly
 * what the pre-session token_version-only design could not do.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { apiMock, resetApiMocks } from "../test/api-mock";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: apiMock };
});

import Sessions from "./Sessions";
import type { SessionRow } from "../types";

const laptop: SessionRow = {
  id: "aaaa",
  label: "Firefox",
  user_agent: "Mozilla/5.0 Firefox/120.0",
  ip_address: "203.0.113.7",
  created_at: "2026-03-01T09:00:00+00:00",
  last_seen_at: "2026-03-01T10:00:00+00:00",
  current: false,
};

const phone: SessionRow = {
  id: "bbbb",
  label: "Safari",
  user_agent: "Mozilla/5.0 Mobile Safari/604.1",
  ip_address: "203.0.113.8",
  created_at: "2026-03-01T09:30:00+00:00",
  last_seen_at: "2026-03-01T10:30:00+00:00",
  current: true,
};

function serve(rows: SessionRow[]) {
  apiMock.get.mockResolvedValue({ data: { sessions: rows } });
}

beforeEach(() => {
  resetApiMocks();
  serve([laptop, phone]);
});

describe("Sessions", () => {
  it("lists each device with its label and address", async () => {
    render(<Sessions refreshKey={0} />);

    expect(await screen.findByText("Firefox")).toBeTruthy();
    expect(screen.getByText("Safari")).toBeTruthy();
    expect(screen.getByText(/203\.0\.113\.8/)).toBeTruthy();
  });

  it("marks the device it is running on and offers no revoke for it", async () => {
    // Revoking the session you are using would log you out of your own browser
    // without meaning to; sign out is the deliberate way to do that.
    render(<Sessions refreshKey={0} />);

    await screen.findByText("Safari");
    expect(screen.getByText(/this device/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /^revoke$/i })).toHaveLength(1);
  });

  it("revokes another device without touching this one", async () => {
    const user = userEvent.setup();
    apiMock.delete.mockResolvedValue({ data: { msg: "Session revoked", was_current: false } });

    render(<Sessions refreshKey={0} />);
    await user.click(await screen.findByRole("button", { name: /^revoke$/i }));

    await waitFor(() => expect(apiMock.delete).toHaveBeenCalledWith("/account/sessions/aaaa"));
    // The revoked row disappears; this device is still listed.
    await waitFor(() => expect(screen.queryByText("Firefox")).toBeNull());
    expect(screen.getByText("Safari")).toBeTruthy();
  });

  it("offers sign-out-everywhere only when there is more than one session", async () => {
    serve([phone]);
    render(<Sessions refreshKey={0} />);

    await screen.findByText("Safari");
    expect(screen.queryByRole("button", { name: /sign out everywhere/i })).toBeNull();
  });

  it("signs out everywhere on request", async () => {
    const user = userEvent.setup();
    apiMock.delete.mockResolvedValue({ data: { msg: "Signed out everywhere" } });

    render(<Sessions refreshKey={0} />);
    await user.click(await screen.findByRole("button", { name: /sign out everywhere/i }));

    await waitFor(() => expect(apiMock.delete).toHaveBeenCalledWith("/account/sessions"));
    await waitFor(() => expect(screen.getByText(/no other active sessions/i)).toBeTruthy());
  });

  it("says so when the only session is this one", async () => {
    serve([phone]);
    render(<Sessions refreshKey={0} />);

    expect(await screen.findByText(/no other active sessions/i)).toBeTruthy();
  });

  it("reports a failed revocation instead of silently dropping the row", async () => {
    const user = userEvent.setup();
    apiMock.delete.mockRejectedValue({
      response: { status: 404, data: { msg: "No such session" } },
    });

    render(<Sessions refreshKey={0} />);
    await user.click(await screen.findByRole("button", { name: /^revoke$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/no such session/i);
    expect(screen.getByText("Firefox")).toBeTruthy();
  });

  it("survives a partial payload rather than throwing", async () => {
    apiMock.get.mockResolvedValue({ data: {} });

    render(<Sessions refreshKey={0} />);

    expect(await screen.findByText(/no other active sessions/i)).toBeTruthy();
  });
});
