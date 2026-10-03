/**
 * Registration. The regression these pin: the backend accepted a
 * one-character password, so the form mirrors those rules to give an instant
 * answer instead of a round trip.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } };
});

import { api } from "../api";
import Register from "./Register.jsx";

/** Fill the register form specifically, not the login one beside it. */
function registerForm() {
  return screen.getByRole("button", { name: /register/i }).closest("form");
}

beforeEach(() => {
  api.post.mockReset();
  api.post.mockResolvedValue({ data: { msg: "User registered" } });
});

describe("Register", () => {
  it("creates an account and reports the username upward", async () => {
    const onRegistered = vi.fn();
    const user = userEvent.setup();

    render(<Register onRegistered={onRegistered} />);
    const form = registerForm();
    await user.type(within(form).getByLabelText(/username/i), "alice");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    await waitFor(() => expect(onRegistered).toHaveBeenCalledWith("alice", false));
    expect(api.post).toHaveBeenCalledWith("/auth/register", {
      username: "alice",
      password: "correct-horse",
    });
  });

  it("sends an email when one is given, and reports it upward", async () => {
    const onRegistered = vi.fn();
    const user = userEvent.setup();

    render(<Register onRegistered={onRegistered} />);
    const form = registerForm();
    await user.type(within(form).getByLabelText(/username/i), "bob");
    await user.type(within(form).getByLabelText(/email/i), "bob@example.com");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    await waitFor(() => expect(onRegistered).toHaveBeenCalledWith("bob", true));
    expect(api.post).toHaveBeenCalledWith("/auth/register", {
      username: "bob",
      password: "correct-horse",
      email: "bob@example.com",
    });
  });

  it("rejects a malformed email before sending", async () => {
    const user = userEvent.setup();

    render(<Register onRegistered={vi.fn()} />);
    const form = registerForm();
    await user.type(within(form).getByLabelText(/username/i), "carol");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");

    // type="email" makes userEvent refuse to type junk, and the browser's own
    // constraint validation would block submit before React ever runs. Set the
    // value directly and submit, to exercise our guard specifically.
    const email = within(form).getByLabelText(/email/i);
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set.call(
      email,
      "not-an-email"
    );
    email.dispatchEvent(new Event("input", { bubbles: true }));

    fireEvent.submit(form);

    expect(await screen.findByRole("alert")).toHaveTextContent(/valid email/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("omits the email field entirely when blank", async () => {
    // Sending email: null would not be the same as "not supplied".
    const user = userEvent.setup();

    render(<Register onRegistered={vi.fn()} />);
    const form = registerForm();
    await user.type(within(form).getByLabelText(/username/i), "dave");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post.mock.calls[0][1]).not.toHaveProperty("email");
  });

  it("surfaces an email-already-registered conflict", async () => {
    api.post.mockRejectedValue({
      response: { status: 409, data: { msg: "Email already registered" } },
    });
    const user = userEvent.setup();

    render(<Register onRegistered={vi.fn()} />);
    const form = registerForm();
    await user.type(within(form).getByLabelText(/username/i), "erin");
    await user.type(within(form).getByLabelText(/email/i), "erin@example.com");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already registered/i);
  });

  it("rejects a password under eight characters", async () => {
    const user = userEvent.setup();

    render(<Register onRegistered={vi.fn()} />);
    const form = registerForm();
    await user.type(within(form).getByLabelText(/username/i), "alice");
    await user.type(within(form).getByLabelText(/password/i), "short");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/at least 8 characters/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("rejects a username under three characters", async () => {
    const user = userEvent.setup();

    render(<Register onRegistered={vi.fn()} />);
    const form = registerForm();
    await user.type(within(form).getByLabelText(/username/i), "ab");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/at least 3 characters/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("rejects usernames with unsupported characters", async () => {
    const user = userEvent.setup();

    render(<Register onRegistered={vi.fn()} />);
    const form = registerForm();
    await user.type(within(form).getByLabelText(/username/i), "bad name");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/letters, digits, dots/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("surfaces a duplicate-username conflict from the server", async () => {
    api.post.mockRejectedValue({
      response: { status: 409, data: { msg: "Username already taken" } },
    });
    const user = userEvent.setup();

    render(<Register onRegistered={vi.fn()} />);
    const form = registerForm();
    await user.type(within(form).getByLabelText(/username/i), "alice");
    await user.type(within(form).getByLabelText(/password/i), "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already taken/i);
  });

  it("clears the password after a successful registration", async () => {
    const user = userEvent.setup();

    render(<Register onRegistered={vi.fn()} />);
    const form = registerForm();
    const password = within(form).getByLabelText(/password/i);
    await user.type(within(form).getByLabelText(/username/i), "alice");
    await user.type(password, "correct-horse");
    await user.click(within(form).getByRole("button", { name: /register/i }));

    // The user has to type the password again to log in, so do not keep it.
    await waitFor(() => expect(password.value).toBe(""));
  });

  it("hints the minimum length on the password field", () => {
    render(<Register onRegistered={vi.fn()} />);

    expect(within(registerForm()).getByLabelText(/password/i)).toHaveAttribute("minlength", "8");
  });

  it("uses a new-password autocomplete hint", () => {
    render(<Register onRegistered={vi.fn()} />);

    expect(within(registerForm()).getByLabelText(/password/i)).toHaveAttribute(
      "autocomplete",
      "new-password"
    );
  });
});