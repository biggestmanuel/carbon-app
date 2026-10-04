/**
 * The second half of a login.
 *
 * The behaviour worth guarding is narrow but load-bearing: a correct password
 * must NOT be treated as a successful login, and nothing may be persisted
 * client-side between the two halves.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { resetMfaMocks, verifySecondFactorMock } from "../test/api-mock";
import type { MfaCheckResponse } from "../types";

// Mocked by name rather than by replacing the axios instance: verifySecondFactor
// is a named export that closes over the real `api`, so swapping the instance
// would leave the component calling the live transport.
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    verifySecondFactor: verifySecondFactorMock,
    errorMessage: actual.errorMessage,
  };
});

import MfaLogin from "./MfaLogin";

const PENDING = "pending-token-value";

function renderIt(overrides?: { onCancel?: () => void }) {
  const onAuthenticated = vi.fn();
  const onCancel = overrides?.onCancel ?? vi.fn();
  render(
    <MfaLogin pendingToken={PENDING} onAuthenticated={onAuthenticated} onCancel={onCancel} />
  );
  return { onAuthenticated, onCancel };
}

beforeEach(() => {
  resetMfaMocks();
});

describe("MfaLogin", () => {
  it("sends the pending token and the code", async () => {
    const user = userEvent.setup();
    renderIt();

    await user.type(screen.getByLabelText(/authentication code/i), "123456");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() =>
      expect(verifySecondFactorMock).toHaveBeenCalledWith(PENDING, "123456")
    );
  });

  it("reports the username upward once the code is accepted", async () => {
    const user = userEvent.setup();
    const { onAuthenticated } = renderIt();

    await user.type(screen.getByLabelText(/authentication code/i), "123456");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("alice"));
  });

  it("never asks for a password", async () => {
    // The password was already accepted. Asking again would be a sign the first
    // step was not actually committed to.
    renderIt();
    expect(screen.queryByLabelText(/^password$/i)).toBeNull();
  });

  it("refuses to submit an empty code", async () => {
    const user = userEvent.setup();
    renderIt();

    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    expect(verifySecondFactorMock).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/enter the code/i);
  });

  it("trims the code before sending", async () => {
    // Codes get pasted, and a trailing space from a clipboard would otherwise
    // become a guaranteed rejection.
    const user = userEvent.setup();
    renderIt();

    await user.type(screen.getByLabelText(/authentication code/i), " 123456 ");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() =>
      expect(verifySecondFactorMock).toHaveBeenCalledWith(PENDING, "123456")
    );
  });

  it("shows the server's message on a wrong code", async () => {
    verifySecondFactorMock.mockRejectedValue({
      response: { status: 401, data: { msg: "That code is not valid." } },
    });
    const user = userEvent.setup();
    renderIt();

    await user.type(screen.getByLabelText(/authentication code/i), "000000");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/not valid/i);
  });

  it("clears the field after a rejection", async () => {
    // TOTP codes are single-use server-side, so resending the same one would
    // fail with a message indistinguishable from a wrong code. Clearing it makes
    // the retry meaningful.
    verifySecondFactorMock.mockRejectedValue({
      response: { status: 401, data: { msg: "That code is not valid." } },
    });
    const user = userEvent.setup();
    renderIt();

    const input = screen.getByLabelText(/authentication code/i) as HTMLInputElement;
    await user.type(input, "000000");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() => expect(input.value).toBe(""));
  });

  it("does not treat a rejection as a sign-in", async () => {
    verifySecondFactorMock.mockRejectedValue({
      response: { status: 401, data: { msg: "That code is not valid." } },
    });
    const user = userEvent.setup();
    const { onAuthenticated } = renderIt();

    await user.type(screen.getByLabelText(/authentication code/i), "000000");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    await screen.findByRole("alert");
    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  it("mentions recovery codes, so a lost phone has a route", () => {
    renderIt();
    expect(screen.getByText(/recovery code/i)).toBeTruthy();
  });

  it("lets the user back out to the password form", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderIt();

    await user.click(screen.getByRole("button", { name: /different account/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("offers the code field the platform's autofill hint", () => {
    // This is what lets iOS and Android offer the code straight from the
    // authenticator app, which is most of the benefit of having one.
    renderIt();
    const input = screen.getByLabelText(/authentication code/i);
    expect(input.getAttribute("autocomplete")).toBe("one-time-code");
    expect(input.getAttribute("inputmode")).toBe("numeric");
  });

  it("is not a number input", () => {
    // type="number" lets a browser accept "1e5" and strips leading zeros, and
    // 000123 is a valid code that has to survive intact.
    renderIt();
    const input = screen.getByLabelText(/authentication code/i);
    expect(input.getAttribute("type")).not.toBe("number");
  });

  it("does not store the pending token anywhere persistent", () => {
    renderIt();

    // The token lives in React state passed as a prop and is sent once. Nothing
    // writes it to storage, where page scripts could read it.
    expect(window.localStorage.getItem("pending_token")).toBeNull();
    expect(window.sessionStorage.getItem("pending_token")).toBeNull();
  });

  it("disables the button while a check is in flight", async () => {
    let release: (value: MfaCheckResponse) => void = () => {};
    verifySecondFactorMock.mockReturnValue(
      new Promise<MfaCheckResponse>((resolve) => {
        release = resolve;
      })
    );
    const user = userEvent.setup();
    renderIt();

    await user.type(screen.getByLabelText(/authentication code/i), "123456");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));

    // Without this, a double-tap sends two codes -- and the second is spent, so
    // it fails with a message that looks like the first was wrong.
    const button = screen.getByRole("button", { name: /checking/i }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    release({
      msg: "Logged in",
      username: "alice",
      email_verified: true,
      second_factor: "totp",
    });
    await waitFor(() => expect(verifySecondFactorMock).toHaveBeenCalledTimes(1));
  });
});