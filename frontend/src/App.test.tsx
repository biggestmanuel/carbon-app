/**
 * Session routing. The bug this guards: on first load with no session, the
 * bootstrap /auth/me 401 was treated as an expired session, so every brand-new
 * visitor was greeted with "Your session has ended". A 401 there is simply the
 * answer "you are not logged in".
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  apiMock,
  fetchSessionMock,
  resetApiMocks,
  resolveAllWith,
  setSessionExpiredHandlerMock,
} from "./test/api-mock";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    api: apiMock,
    fetchSession: fetchSessionMock,
    setSessionExpiredHandler: setSessionExpiredHandlerMock,
  };
});

import App from "./App";

const ALICE = { id: 1, username: "alice", has_email: false, email_verified: false };

beforeEach(() => {
  resetApiMocks();
  resolveAllWith({});
  // Each test sets its own URL; a leftover ?token= would open the reset screen.
  window.history.replaceState({}, "", "/");
});

describe("App session routing", () => {
  it("shows the login screen with no expiry banner when there is no session", async () => {
    // The regression. This 401 is normal, not an expiry.
    fetchSessionMock.mockRejectedValue({
      response: { status: 401, data: { msg: "Authentication required" } },
    });

    render(<App />);

    // Register and Login both have a username field, so scope to the login form.
    expect(await screen.findByRole("button", { name: /^log in$/i })).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.queryByText(/session has ended/i)).toBeNull();
  });

  it("renders the dashboard for a valid session", async () => {
    fetchSessionMock.mockResolvedValue(ALICE);

    render(<App />);

    await waitFor(() => expect(screen.getByText(/signed in as alice/i)).toBeTruthy());
    expect(screen.getByRole("button", { name: /log out/i })).toBeTruthy();
  });

  it("shows a checking state before the probe resolves", async () => {
    let release!: (value: unknown) => void;
    fetchSessionMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        })
    );

    render(<App />);

    expect(screen.getByText(/checking your session/i)).toBeTruthy();

    release(ALICE);
    await waitFor(() => expect(screen.queryByText(/checking your session/i)).toBeNull());
  });

  it("registers a handler for mid-session expiry", async () => {
    fetchSessionMock.mockResolvedValue(ALICE);

    render(<App />);

    await waitFor(() => expect(setSessionExpiredHandlerMock).toHaveBeenCalled());
  });

  it("logs out and clears the session on demand", async () => {
    fetchSessionMock.mockResolvedValue(ALICE);
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /log out/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith("/auth/logout"));
    expect(await screen.findByRole("button", { name: /^log in$/i })).toBeTruthy();
  });

  it("returns to the login screen even if the logout call fails", async () => {
    fetchSessionMock.mockResolvedValue(ALICE);
    apiMock.post.mockRejectedValue({ request: {} });
    const user = userEvent.setup();

    render(<App />);
    await user.click(await screen.findByRole("button", { name: /log out/i }));

    // A dead network must not strand the user on a dashboard they cannot leave.
    expect(await screen.findByRole("button", { name: /^log in$/i })).toBeTruthy();
  });

  it("switches to the dashboard after a successful login", async () => {
    fetchSessionMock.mockRejectedValue({ response: { status: 401 } });
    const user = userEvent.setup();

    render(<App />);
    const loginButton = await screen.findByRole("button", { name: /^log in$/i });
    const loginForm = loginButton.closest("form") as HTMLFormElement;

    // Login posts through the mocked api and reports the username upward, then
    // App re-probes to fill in the rest of the account.
    apiMock.post.mockImplementation((url: string) =>
      url === "/auth/login"
        ? Promise.resolve({ data: { msg: "Logged in", username: "alice" } })
        : Promise.resolve({ data: {} })
    );
    fetchSessionMock.mockResolvedValue(ALICE);

    await user.type(within(loginForm).getByLabelText(/username/i), "alice");
    await user.type(within(loginForm).getByLabelText(/password/i), "correct-horse");
    await user.click(loginButton);

    await waitFor(() => expect(screen.getByText(/signed in as alice/i)).toBeTruthy());
  });

  it("tells a new account holder to confirm their address", async () => {
    fetchSessionMock.mockRejectedValue({ response: { status: 401 } });
    const user = userEvent.setup();

    render(<App />);
    const registerButton = await screen.findByRole("button", { name: /register/i });
    const form = registerButton.closest("form") as HTMLFormElement;

    apiMock.post.mockResolvedValue({ data: { msg: "User registered" } });

    await user.type(within(form).getByLabelText(/username/i), "bob");
    await user.type(within(form).getByLabelText(/email/i), "bob@example.com");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    // Until the address is confirmed the account cannot be recovered, so say so.
    expect(await screen.findByText(/check your email to confirm it/i)).toBeTruthy();
  });

  it("does not mention email when none was given", async () => {
    fetchSessionMock.mockRejectedValue({ response: { status: 401 } });
    const user = userEvent.setup();

    render(<App />);
    const registerButton = await screen.findByRole("button", { name: /register/i });
    const form = registerButton.closest("form") as HTMLFormElement;

    apiMock.post.mockResolvedValue({ data: { msg: "User registered" } });

    await user.type(within(form).getByLabelText(/username/i), "bob");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    expect(await screen.findByText(/you can log in now/i)).toBeTruthy();
  });
});

describe("App emailed links", () => {
  it("opens the reset form for a link with a token", async () => {
    window.history.replaceState({}, "", "/reset-password?token=abc123");

    render(<App />);

    expect(await screen.findByRole("button", { name: /update password/i })).toBeTruthy();
  });

  it("opens the confirmation form for a verification link", async () => {
    window.history.replaceState({}, "", "/verify-email?token=abc123");

    render(<App />);

    expect(await screen.findByRole("button", { name: /confirm this address/i })).toBeTruthy();
  });

  it("does not probe for a session on a link page", async () => {
    // Nobody is logged in on the device that clicks an emailed link, so asking
    // would only produce a misleading 401.
    window.history.replaceState({}, "", "/reset-password?token=abc123");

    render(<App />);

    await screen.findByRole("button", { name: /update password/i });
    expect(fetchSessionMock).not.toHaveBeenCalled();
  });
});
