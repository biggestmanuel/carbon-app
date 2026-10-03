/**
 * Login behaviour, including the bug where a wrong password showed a
 * "session expired" banner instead of the credentials error. The banner text
 * is asserted here because that mix-up is what the fix was about.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { post: vi.fn(), get: vi.fn() } };
});

import { api } from "../api";
import Login from "./Login.jsx";

beforeEach(() => {
  api.post.mockReset();
});

describe("Login", () => {
  it("signs in and reports the username upward", async () => {
    api.post.mockResolvedValue({ data: { msg: "Logged in", username: "alice" } });
    const onAuthenticated = vi.fn();
    const user = userEvent.setup();

    render(<Login onAuthenticated={onAuthenticated} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("alice"));
    expect(api.post).toHaveBeenCalledWith("/auth/login", {
      username: "alice",
      password: "correct-horse",
    });
  });

  it("trims the username before sending", async () => {
    api.post.mockResolvedValue({ data: { username: "alice" } });
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.type(screen.getByLabelText(/username/i), "  alice  ");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post.mock.calls[0][1].username).toBe("alice");
  });

  it("shows a credentials error, never a session-expired banner", async () => {
    api.post.mockRejectedValue({
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
    expect(api.post).not.toHaveBeenCalled();
  });

  it("reports an unreachable backend", async () => {
    api.post.mockRejectedValue({ request: {} });
    const user = userEvent.setup();

    render(<Login onAuthenticated={vi.fn()} />);
    await user.type(screen.getByLabelText(/username/i), "alice");
    await user.type(screen.getByLabelText(/password/i), "correct-horse");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/backend running/i);
  });

  it("reports a rate limit with the server's wording", async () => {
    api.post.mockRejectedValue({
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
    let release;
    api.post.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
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