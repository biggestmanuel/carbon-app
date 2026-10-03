/**
 * Email confirmation.
 *
 * The prompt matters because until it is done the account cannot be recovered:
 * the backend refuses to mail a reset link to an unconfirmed address, precisely
 * so a stranger who registered someone else's inbox is not handed their account.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { apiMock, resetApiMocks } from "../test/api-mock";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: apiMock };
});

import VerifyEmail, { VerifyEmailPage } from "./VerifyEmail";

beforeEach(() => {
  resetApiMocks();
  apiMock.post.mockResolvedValue({ data: { msg: "Check your inbox." } });
});

afterEach(() => {
  window.history.replaceState({}, "", "/");
});

describe("VerifyEmail prompt", () => {
  it("renders nothing when the address is already confirmed", () => {
    const { container } = render(
      <VerifyEmail verified onVerified={vi.fn()} />
    );

    expect(container.firstChild).toBeNull();
  });

  it("shows the masked address it will confirm", () => {
    render(<VerifyEmail email="a***e@example.com" verified={false} onVerified={vi.fn()} />);

    expect(screen.getByText(/a\*\*\*e@example\.com/)).toBeTruthy();
  });

  it("explains that reset is blocked until it is confirmed", () => {
    render(<VerifyEmail email="a***e@example.com" verified={false} onVerified={vi.fn()} />);

    // Without this, a user who forgets their password sees nothing arrive and
    // has no idea why.
    expect(screen.getByText(/reset is refused/i)).toBeTruthy();
  });

  it("requests a confirmation link", async () => {
    const user = userEvent.setup();
    render(<VerifyEmail email="a***e@example.com" verified={false} onVerified={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /send confirmation link/i }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/account/verify-email/request")
    );
    expect(await screen.findByRole("status")).toHaveTextContent(/check your inbox/i);
  });

  it("offers the development token as a link when there is no inbox", async () => {
    apiMock.post.mockResolvedValue({ data: { msg: "Sent.", dev_token: "vtok123" } });
    const user = userEvent.setup();
    render(<VerifyEmail email="a***e@example.com" verified={false} onVerified={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /send confirmation link/i }));

    expect(await screen.findByText(/token=vtok123/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /i have confirmed it/i })).toBeTruthy();
  });

  it("reports a failed send", async () => {
    apiMock.post.mockRejectedValue({
      response: { status: 502, data: { msg: "Could not send the confirmation email." } },
    });
    const user = userEvent.setup();
    render(<VerifyEmail email="a***e@example.com" verified={false} onVerified={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /send confirmation link/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not send/i);
  });
});

describe("VerifyEmailPage", () => {
  it("confirms the token from the URL", async () => {
    window.history.replaceState({}, "", "/verify-email?token=vtok123");
    apiMock.post.mockResolvedValue({ data: { email_verified: true } });

    const user = userEvent.setup();
    render(<VerifyEmailPage />);
    await user.click(screen.getByRole("button", { name: /confirm this address/i }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/account/verify-email/confirm", {
        token: "vtok123",
      })
    );
    expect(await screen.findByText(/email confirmed/i)).toBeTruthy();
    expect(screen.getByText(/reset your password/i)).toBeTruthy();
  });

  it("refuses to submit with no token", () => {
    render(<VerifyEmailPage />);

    expect(screen.getByRole("button", { name: /confirm this address/i })).toBeDisabled();
  });

  it("reports an expired link without guessing why", async () => {
    window.history.replaceState({}, "", "/verify-email?token=old");
    apiMock.post.mockRejectedValue({
      response: { status: 400, data: { msg: "This confirmation link is invalid or has expired." } },
    });

    const user = userEvent.setup();
    render(<VerifyEmailPage />);
    await user.click(screen.getByRole("button", { name: /confirm this address/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid or has expired/i);
  });
});
