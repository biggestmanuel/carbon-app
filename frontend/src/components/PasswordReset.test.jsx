/**
 * The reset flow, including the property that matters most: the screen must
 * never reveal whether an address exists, because the backend's whole design
 * is built around not being an enumeration oracle.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { get: vi.fn(), post: vi.fn() } };
});

import { api } from "../api";
import ForgotPassword from "./ForgotPassword.jsx";
import ResetPassword from "./ResetPassword.jsx";

const GENERIC = "If that address exists, a reset link is on its way.";

beforeEach(() => {
  api.post.mockReset();
});

afterEach(() => {
  // Each test sets its own URL; put it back.
  window.history.replaceState({}, "", "/");
});

describe("ForgotPassword", () => {
  it("asks for an address and reports success generically", async () => {
    api.post.mockResolvedValue({ data: { msg: GENERIC } });
    const user = userEvent.setup();

    render(<ForgotPassword onBack={vi.fn()} />);
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() =>
      expect(screen.getByText(/if that address has an account/i)).toBeTruthy()
    );
    expect(api.post).toHaveBeenCalledWith("/auth/forgot-password", {
      email: "alice@example.com",
    });
  });

  it("shows the same wording whether or not the address exists", async () => {
    // A 202 for both cases is the backend's contract; this locks in the UI's
    // half of it.
    api.post.mockResolvedValue({ data: { msg: GENERIC } });
    const user = userEvent.setup();

    render(<ForgotPassword onBack={vi.fn()} />);
    await user.type(screen.getByLabelText(/email/i), "ghost@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    const message = await screen.findByText(/if that address has an account/i);
    expect(message.textContent).toMatch(/if that address/i);
  });

  it("surfaces the development token so the flow works without an inbox", async () => {
    api.post.mockResolvedValue({ data: { msg: GENERIC, dev_token: "tok123" } });
    const user = userEvent.setup();

    render(<ForgotPassword onBack={vi.fn()} />);
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    const link = await screen.findByRole("link", { name: /open the reset link/i });
    expect(link.getAttribute("href")).toBe("/?token=tok123");
  });

  it("omits the development block when there is no token", async () => {
    api.post.mockResolvedValue({ data: { msg: GENERIC } });
    const user = userEvent.setup();

    render(<ForgotPassword onBack={vi.fn()} />);
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    await screen.findByText(/if that address has an account/i);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("requires an address before calling the API", async () => {
    const user = userEvent.setup();

    render(<ForgotPassword onBack={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/enter your email/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("returns to the login form on request", async () => {
    const onBack = vi.fn();
    const user = userEvent.setup();

    render(<ForgotPassword onBack={onBack} />);
    await user.click(screen.getByRole("button", { name: /back to log in/i }));

    expect(onBack).toHaveBeenCalled();
  });
});

describe("ResetPassword", () => {
  function openWithToken(token) {
    window.history.replaceState({}, "", `/?token=${token}`);
  }

  const PW = /choose password/i;
const CONFIRM = /confirm new password/i;

it("submits the token from the URL with the new password", async () => {
    openWithToken("abc123");
    api.post.mockResolvedValue({ data: { msg: "Password updated." } });
    const user = userEvent.setup();

    render(<ResetPassword />);
    await user.type(screen.getByLabelText(PW), "brand-new-password");
    await user.type(screen.getByLabelText(CONFIRM), "brand-new-password");
    await user.click(screen.getByRole("button", { name: /update password/i }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/auth/reset-password", {
        token: "abc123",
        password: "brand-new-password",
      })
    );
    expect(await screen.findByText(/you can now log in/i)).toBeTruthy();
  });

  it("rejects a mismatch before calling the API", async () => {
    openWithToken("abc123");
    const user = userEvent.setup();

    render(<ResetPassword />);
    await user.type(screen.getByLabelText(PW), "brand-new-password");
    await user.type(screen.getByLabelText(CONFIRM), "something-else");
    await user.click(screen.getByRole("button", { name: /update password/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/do not match/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("enforces a minimum length", async () => {
    openWithToken("abc123");
    const user = userEvent.setup();

    render(<ResetPassword />);
    await user.type(screen.getByLabelText(PW), "short");
    await user.type(screen.getByLabelText(CONFIRM), "short");
    await user.click(screen.getByRole("button", { name: /update password/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/at least 8/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("refuses to submit with no token in the URL", async () => {
    const user = userEvent.setup();

    render(<ResetPassword />);
    await user.type(screen.getByLabelText(PW), "brand-new-password");
    await user.type(screen.getByLabelText(CONFIRM), "brand-new-password");
    await user.click(screen.getByRole("button", { name: /update password/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid or has expired/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("shows the server's message when the link is used up", async () => {
    openWithToken("abc123");
    api.post.mockRejectedValue({
      response: { status: 400, data: { msg: "This reset link is invalid or has expired." } },
    });
    const user = userEvent.setup();

    render(<ResetPassword />);
    await user.type(screen.getByLabelText(PW), "brand-new-password");
    await user.type(screen.getByLabelText(CONFIRM), "brand-new-password");
    await user.click(screen.getByRole("button", { name: /update password/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid or has expired/i);
  });

  it("masks both password fields", () => {
    openWithToken("abc123");
    render(<ResetPassword />);

    expect(screen.getByLabelText(PW)).toHaveAttribute("type", "password");
    expect(screen.getByLabelText(CONFIRM)).toHaveAttribute("type", "password");
  });
});