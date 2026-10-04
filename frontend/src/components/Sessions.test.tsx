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
  label: "Firefox on Linux",
  browser: "Firefox",
  os: "Linux",
  user_agent: "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
  ip_address: "203.0.113.7",
  created_at: "2026-03-01T09:00:00+00:00",
  last_seen_at: "2026-03-01T10:00:00+00:00",
  current: false,
  new_location: false,
  new_device: false,
  unrecognised: false,
};

const phone: SessionRow = {
  id: "bbbb",
  label: "Safari on iPhone",
  browser: "Safari",
  os: "iPhone",
  user_agent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile/15E148 Safari/604.1",
  ip_address: "203.0.113.8",
  created_at: "2026-03-01T09:30:00+00:00",
  last_seen_at: "2026-03-01T10:30:00+00:00",
  current: true,
  new_location: false,
  new_device: false,
  unrecognised: false,
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

    expect(await screen.findByText("Firefox on Linux")).toBeTruthy();
    expect(screen.getByText("Safari on iPhone")).toBeTruthy();
    expect(screen.getByText(/203\.0\.113\.8/)).toBeTruthy();
  });

  it("says what the list is for", async () => {
    render(<Sessions refreshKey={0} />);

    expect(screen.getByText(/revoke anything you do not recognise/i)).toBeTruthy();
  });

  it("does not flag a session the account has seen before", async () => {
    render(<Sessions refreshKey={0} />);

    await screen.findByText("Firefox on Linux");
    expect(screen.queryByText(/new device|new location/)).toBeNull();
  });

  it("flags a session from an unfamiliar address", async () => {
    serve([
      { ...phone, id: "cccc", new_location: true, unrecognised: true },
      laptop,
    ]);
    render(<Sessions refreshKey={0} />);

    expect(await screen.findByText("new location")).toBeTruthy();
  });

  it("distinguishes a new device from a new location", async () => {
    serve([
      { ...phone, id: "dddd", new_device: true, unrecognised: true },
      laptop,
    ]);
    render(<Sessions refreshKey={0} />);

    expect(await screen.findByText("new device")).toBeTruthy();
  });

  it("says so when both are unfamiliar", async () => {
    serve([
      {
        ...phone, id: "eeee", new_location: true, new_device: true, unrecognised: true,
      },
      laptop,
    ]);
    render(<Sessions refreshKey={0} />);

    expect(await screen.findByText("new device and location")).toBeTruthy();
  });

  it("marks the device it is running on and offers no revoke for it", async () => {
    // Revoking the session you are using would log you out of your own browser
    // without meaning to; sign out is the deliberate way to do that.
    render(<Sessions refreshKey={0} />);

    await screen.findByText("Safari on iPhone");
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
    await waitFor(() => expect(screen.queryByText("Firefox on Linux")).toBeNull());
    expect(screen.getByText("Safari on iPhone")).toBeTruthy();
  });

  it("offers sign-out-everywhere only when there is more than one session", async () => {
    serve([phone]);
    render(<Sessions refreshKey={0} />);

    await screen.findByText("Safari on iPhone");
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
    expect(screen.getByText("Firefox on Linux")).toBeTruthy();
  });

  it("survives a partial payload rather than throwing", async () => {
    apiMock.get.mockResolvedValue({ data: {} });

    render(<Sessions refreshKey={0} />);

    expect(await screen.findByText(/no other active sessions/i)).toBeTruthy();
  });
});
