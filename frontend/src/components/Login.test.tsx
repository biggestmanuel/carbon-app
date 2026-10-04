/**
 * Login behaviour, including the bug where a wrong password showed a
 * "session expired" banner instead of the credentials error. The banner text
 * is asserted here because that mix-up is what the fix was about.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { apiMock } from "../test/api-mock";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: apiMock, verifySecondFactor: verifySecondFactorMock };
});

import { resetApiMocks, verifySecondFactorMock, resetMfaMocks } from "../test/api-mock";

import Login from "./Login";

beforeEach(() => {
  resetApiMocks();
  resetMfaMocks();
});

describe("Login", () => {
  it("signs in and reports the username upward", async () => {
    apiMock.post.mockResolvedValue({ data: { msg: "Logged in", username: "alice" } });
    const onAuthenticated = vi.fn();
    const user = userEvent.setup();

    render(<Login onAuthenticated={onAuthenticated} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("alice"));
    expect(apiMock.post).toHaveBeenCalledWith("/auth/login", {
      username: "alice",
      password: "correct-horse",
    });
  });

  it("trims the username before sending", async () => {
    apiMock.post.mockResolvedValue({ data: { username: "alice" } });
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.type(screen.getByLabelText(/username/i), "  alice  ");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalled());
    const sent = apiMock.post.mock.calls[0]?.[1] as { username: string };
    expect(sent.username).toBe("alice");
  });
});

describe("Login with a second factor", () => {
    it("shows the code step instead of signing in", async () => {
    // The password was correct but no session exists yet. Treating this as a
    // completed login would leave the user on a dashboard with no cookies.
    apiMock.post.mockResolvedValue({
      data: { msg: "Second factor required", mfa_required: true, pending_token: "abc123" },
    });
    const onAuthenticated = vi.fn();
    const user = userEvent.setup();

    render(<Login onAuthenticated={onAuthenticated} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByLabelText(/authentication code/i)).toBeTruthy();
    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  it("does not send a second login request", async () => {
    apiMock.post.mockResolvedValue({
      data: { msg: "Second factor required", mfa_required: true, pending_token: "abc123" },
    });
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await screen.findByLabelText(/authentication code/i);
    expect(apiMock.post).toHaveBeenCalledTimes(1);
  });

    it("unmounts the password field before the code step", async () => {
    // The code form replaces the password form outright. Checking the old field's
    // value would be vacuous if the element is gone: a detached input keeps
    // whatever it last held, readable by anything still holding a reference.
    apiMock.post.mockResolvedValue({
      data: { msg: "Second factor required", mfa_required: true, pending_token: "abc123" },
    });
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await screen.findByLabelText(/authentication code/i);
    expect(screen.queryByLabelText(/^password$/i)).toBeNull();
    // And the password is not sitting in the rendered markup anywhere.
    expect(document.body.innerHTML).not.toContain("correct-horse");
  });

    it("returns to the password form on request", async () => {
    apiMock.post.mockResolvedValue({
      data: { msg: "Second factor required", mfa_required: true, pending_token: "abc123" },
    });
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await user.click(await screen.findByRole("button", { name: /different account/i }));
    expect(screen.getByLabelText(/^password$/i)).toBeTruthy();
  });

    it("completes the login once the code is accepted", async () => {
    // The whole point: the password half and the code half together.
    apiMock.post.mockResolvedValue({
      data: { msg: "Second factor required", mfa_required: true, pending_token: "abc123" },
    });
    verifySecondFactorMock.mockResolvedValue({
      msg: "Logged in",
      username: "alice",
      email_verified: true,
      second_factor: "totp",
    });
    const onAuthenticated = vi.fn();
    const user = userEvent.setup();

    render(<Login onAuthenticated={onAuthenticated} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await user.type(await screen.findByLabelText(/authentication code/i), "123456");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("alice"));
  });
});

describe("Login without a second factor", () => {
  it("shows a credentials error, never a session-expired banner", async () => {
    apiMock.post.mockRejectedValue({
      response: { status: 401, data: { msg: "Bad credentials" } },
    });
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "wrong-password");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Bad credentials");
    // The regression: this used to render as an expired session instead.
    expect(alert).not.toHaveTextContent(/session/i);
  });

  it("rejects empty credentials without calling the API", async () => {
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/enter a username and password/i);
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("reports an unreachable backend", async () => {
    apiMock.post.mockRejectedValue({ request: {} });
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/backend running/i);
  });

  it("reports a rate limit with the server's wording", async () => {
    apiMock.post.mockRejectedValue({
      response: { status: 429, data: { msg: "Too many requests. Please slow down." } },
    });
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/too many requests/i);
  });

  it("masks the password field and disables the button while submitting", async () => {
    let release!: (value: unknown) => void;
    apiMock.post.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        })
    );
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    expect(screen.getByLabelText(/password/i)).toHaveAttribute("type", "password");

    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /^log in$/i }));

    const pending = await screen.findByRole("button", { name: /logging in/i });
    expect(pending).toBeDisabled();

    release({ data: { username: "alice" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /^log in$/i })).toBeEnabled());
  });
});
