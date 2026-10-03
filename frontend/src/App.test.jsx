/**
 * Session routing. The bug this guards: on first load with no session, the
 * bootstrap /auth/me 401 was treated as an expired session, so every brand-new
 * visitor was greeted with "Your session has ended". A 401 there is simply the
 * answer "you are not logged in".
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Dashboard children call api.get on mount, so every method needs a resolved
// promise. Leaving one undefined throws inside a child and takes the tree down
// with it.
vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal();
  const resolved = (data) => () => Promise.resolve({ data });
  return {
    ...actual,
    api: { get: vi.fn(resolved({})), post: vi.fn(resolved({})) },
    fetchSession: vi.fn(),
    setSessionExpiredHandler: vi.fn(),
  };
});

import { api, fetchSession } from "./api";
import App from "./App.jsx";

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation(() => Promise.resolve({ data: {} }));
  api.post.mockReset();
  api.post.mockImplementation(() => Promise.resolve({ data: {} }));
  fetchSession.mockReset();
});

describe("App session routing", () => {
  it("shows the login screen with no expiry banner when there is no session", async () => {
    // The regression. This 401 is normal, not an expiry.
    fetchSession.mockRejectedValue({ response: { status: 401, data: { msg: "Authentication required" } } });

    render(<App />);

    // Register and Login both have a username field, so scope to the login form.
    expect(await screen.findByRole("button", { name: /^log in$/i })).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.queryByText(/session has ended/i)).toBeNull();
  });

  it("renders the dashboard for a valid session", async () => {
    fetchSession.mockResolvedValue({ id: 1, username: "alice" });

    render(<App />);

    await waitFor(() => expect(screen.getByText(/signed in as alice/i)).toBeTruthy());
    expect(screen.getByRole("button", { name: /log out/i })).toBeTruthy();
  });

  it("shows a checking state before the probe resolves", async () => {
    let release;
    fetchSession.mockImplementation(() => new Promise((resolve) => { release = resolve; }));

    render(<App />);

    expect(screen.getByText(/checking your session/i)).toBeTruthy();

    release({ id: 1, username: "alice" });
    await waitFor(() => expect(screen.queryByText(/checking your session/i)).toBeNull());
  });

  it("registers a handler for mid-session expiry", async () => {
    fetchSession.mockResolvedValue({ id: 1, username: "alice" });
    const { setSessionExpiredHandler } = await import("./api");

    render(<App />);

    await waitFor(() => expect(setSessionExpiredHandler).toHaveBeenCalled());
  });

  it("logs out and clears the session on demand", async () => {
    fetchSession.mockResolvedValue({ id: 1, username: "alice" });
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /log out/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/auth/logout"));
    expect(await screen.findByRole("button", { name: /^log in$/i })).toBeTruthy();
  });

  it("returns to the login screen even if the logout call fails", async () => {
    fetchSession.mockResolvedValue({ id: 1, username: "alice" });
    api.post.mockRejectedValue({ request: {} });
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /log out/i }));

    // A dead network must not strand the user on a dashboard they cannot leave.
    expect(await screen.findByRole("button", { name: /^log in$/i })).toBeTruthy();
  });

  it("switches to the dashboard after a successful login", async () => {
    fetchSession.mockRejectedValue({ response: { status: 401 } });
    const user = userEvent.setup();

    render(<App />);
    const loginButton = await screen.findByRole("button", { name: /^log in$/i });
    const loginForm = loginButton.closest("form");

    // Login posts through the mocked api and reports the username upward.
    api.post.mockImplementation((url) =>
      url === "/auth/login"
        ? Promise.resolve({ data: { msg: "Logged in", username: "alice" } })
        : Promise.resolve({ data: {} })
    );

    await user.type(within(loginForm).getByLabelText(/username/i), "alice");
    await user.type(within(loginForm).getByLabelText(/password/i), "correct-horse");
    await user.click(loginButton);

    await waitFor(() => expect(screen.getByText(/signed in as alice/i)).toBeTruthy());
  });
});