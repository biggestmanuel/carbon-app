/**
 * The second-factor settings panel.
 *
 * The behaviours that matter here are about losing users rather than being
 * attacked: recovery codes are visible exactly once, the seed can be read and
 * copied when a QR code will not scan, and a low code count is surfaced before it
 * reaches zero.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  MFA_ON,
  MFA_SETUP,
  RECOVERY_CODES,
  confirmTotpSetupMock,
  disableTotpMock,
  fetchMfaStatusMock,
  regenerateRecoveryCodesMock,
  resetMfaMocks,
  startTotpSetupMock,
} from "../test/api-mock";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    startTotpSetup: startTotpSetupMock,
    confirmTotpSetup: confirmTotpSetupMock,
    fetchMfaStatus: fetchMfaStatusMock,
    disableTotp: disableTotpMock,
    regenerateRecoveryCodes: regenerateRecoveryCodesMock,
  };
});

// The QR encoder is stubbed: jsdom has no layout, and asserting on rendered
// SVG geometry would test the encoder rather than this component.
vi.mock("qrcode", () => ({
  default: { toString: vi.fn().mockResolvedValue("<svg><rect/></svg>") },
}));

import MfaSettings from "./MfaSettings";

beforeEach(() => {
  resetMfaMocks();
});

describe("MfaSettings", () => {
  it("offers to set up 2FA when it is off", async () => {
    render(<MfaSettings onDisabled={vi.fn()} />);

    expect(
      await screen.findByRole("button", { name: /set up two-factor/i })
    ).toBeTruthy();
  });

  it("says nothing about setup until the status is known", () => {
    // Claiming "off" before the answer arrives would offer to arm a factor that
    // may already be armed.
    fetchMfaStatusMock.mockReturnValue(new Promise(() => {}));
    render(<MfaSettings onDisabled={vi.fn()} />);

    expect(screen.getByText(/checking whether/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /set up two-factor/i })).toBeNull();
  });

  it("shows the on state and the code count", async () => {
    fetchMfaStatusMock.mockResolvedValue(MFA_ON);
    render(<MfaSettings onDisabled={vi.fn()} />);

    expect(await screen.findByText(/is on/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /issue new recovery codes/i })).toBeTruthy();
  });

  describe("enrolment", () => {
    it("shows the secret and a QR code after starting", async () => {
      const user = userEvent.setup();
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.click(await screen.findByRole("button", { name: /set up two-factor/i }));

      expect(await screen.findByText(MFA_SETUP.secret)).toBeTruthy();
      // The QR stands in for the secret on screen, so it has to be there.
      expect(document.querySelector(".totp-qr")).toBeTruthy();
    });

    it("never sends the provisioning URI to a third party", async () => {
      const user = userEvent.setup();
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.click(await screen.findByRole("button", { name: /set up two-factor/i }));
      await screen.findByText(MFA_SETUP.secret);

      // The URI carries the TOTP seed. Rendering it as an <img src> to a hosted
      // QR service would hand the entire second factor to that host, and cache it
      // in whatever proxy sits in front. Assert on the absence of a remote src.
      for (const img of Array.from(document.querySelectorAll("img"))) {
        expect(img.getAttribute("src") ?? "").not.toMatch(/^https?:/);
      }
      expect(document.body.innerHTML).not.toMatch(/qrserver|api\.qrserver\.com/);
    });

    it("offers the key for copying, for when a code will not scan", async () => {
      const user = userEvent.setup();
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.click(await screen.findByRole("button", { name: /set up two-factor/i }));
      expect(await screen.findByRole("button", { name: /copy key/i })).toBeTruthy();
    });

    it("cannot confirm without a code", async () => {
      const user = userEvent.setup();
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.click(await screen.findByRole("button", { name: /set up two-factor/i }));
      const confirm = await screen.findByRole("button", { name: /confirm and turn on/i });

      expect((confirm as HTMLButtonElement).disabled).toBe(true);
      expect(confirmTotpSetupMock).not.toHaveBeenCalled();
    });

    it("confirms with the secret and the code, then reveals the recovery codes", async () => {
      const user = userEvent.setup();
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.click(await screen.findByRole("button", { name: /set up two-factor/i }));
      await user.type(await screen.findByLabelText(/code from your app/i), "123456");
      await user.click(screen.getByRole("button", { name: /confirm and turn on/i }));

      await waitFor(() =>
        expect(confirmTotpSetupMock).toHaveBeenCalledWith(MFA_SETUP.secret, "123456")
      );
      // Only hashes are stored server-side, so this is the one chance to see them.
      expect(await screen.findAllByRole("listitem")).toHaveLength(RECOVERY_CODES.length);
    });

    it("says the codes will not be shown again", async () => {
      const user = userEvent.setup();
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.click(await screen.findByRole("button", { name: /set up two-factor/i }));
      await user.type(await screen.findByLabelText(/code from your app/i), "123456");
      await user.click(screen.getByRole("button", { name: /confirm and turn on/i }));

      expect(await screen.findByText(/never again/i)).toBeTruthy();
    });

    it("reports a rejected confirmation without losing the setup", async () => {
      confirmTotpSetupMock.mockRejectedValue({
        response: { status: 400, data: { msg: "That code is not valid." } },
      });
      const user = userEvent.setup();
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.click(await screen.findByRole("button", { name: /set up two-factor/i }));
      await user.type(await screen.findByLabelText(/code from your app/i), "000000");
      await user.click(screen.getByRole("button", { name: /confirm and turn on/i }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/not valid/i);
      // The secret is still on screen, so a mistyped code is retryable.
      expect(screen.getByText(MFA_SETUP.secret)).toBeTruthy();
    });

    it("can be cancelled without arming anything", async () => {
      const user = userEvent.setup();
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.click(await screen.findByRole("button", { name: /set up two-factor/i }));
      await user.click(await screen.findByRole("button", { name: /^cancel$/i }));

      expect(await screen.findByRole("button", { name: /set up two-factor/i })).toBeTruthy();
      expect(confirmTotpSetupMock).not.toHaveBeenCalled();
    });

    it("surfaces a server that cannot do 2FA at all", async () => {
      startTotpSetupMock.mockRejectedValue({
        response: { status: 503, data: { msg: "Two-factor setup is not configured on this server." } },
      });
      const user = userEvent.setup();
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.click(await screen.findByRole("button", { name: /set up two-factor/i }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/not configured/i);
    });
  });

  describe("recovery codes", () => {
    it("warns when few are left", async () => {
      fetchMfaStatusMock.mockResolvedValue({ ...MFA_ON, recovery_codes_remaining: 2 });
      render(<MfaSettings onDisabled={vi.fn()} />);

      expect(await screen.findByText(/only 2 recovery codes left/i)).toBeTruthy();
    });

    it("does not warn while there are plenty", async () => {
      fetchMfaStatusMock.mockResolvedValue({ ...MFA_ON, recovery_codes_remaining: 10 });
      render(<MfaSettings onDisabled={vi.fn()} />);

      await screen.findByText(/is on/i);
      expect(screen.queryByText(/recovery codes left/i)).toBeNull();
    });

    it("says so plainly when there are none", async () => {
      // Running out means a lost phone requires a password reset that signs out
      // every device. That has to be said, not merely implied by a missing count.
      fetchMfaStatusMock.mockResolvedValue({ ...MFA_ON, recovery_codes_remaining: 0 });
      render(<MfaSettings onDisabled={vi.fn()} />);

      expect(await screen.findByText(/no recovery codes/i)).toBeTruthy();
    });

    it("requires the password before issuing a new set", async () => {
      const user = userEvent.setup();
      fetchMfaStatusMock.mockResolvedValue(MFA_ON);
      render(<MfaSettings onDisabled={vi.fn()} />);

      const button = await screen.findByRole("button", { name: /issue new recovery/i });
      expect((button as HTMLButtonElement).disabled).toBe(true);

      await user.type(screen.getByLabelText(/password, to issue/i), "correct-horse");
      await user.click(screen.getByRole("button", { name: /issue new recovery/i }));

      await waitFor(() =>
        expect(regenerateRecoveryCodesMock).toHaveBeenCalledWith("correct-horse")
      );
    });

    it("reveals the new codes, and clears the password field", async () => {
      const user = userEvent.setup();
      fetchMfaStatusMock.mockResolvedValue(MFA_ON);
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.type(await screen.findByLabelText(/password, to issue/i), "correct-horse");
      await user.click(screen.getByRole("button", { name: /issue new recovery/i }));

      // Indexed access is `string | undefined` under noUncheckedIndexedAccess, so
      // the non-null assertion is on the fixture rather than on a silent
      // `undefined` reaching a matcher.
      expect(await screen.findByText(RECOVERY_CODES[0]!)).toBeTruthy();
      // The panel has been replaced by the codes view, so the password field is
      // gone -- the value did not merely get cleared in place.
      expect(screen.queryByLabelText(/password, to issue/i)).toBeNull();
    });

    it("reports a wrong password rather than silently doing nothing", async () => {
      regenerateRecoveryCodesMock.mockRejectedValue({
        response: { status: 403, data: { msg: "Password is incorrect" } },
      });
      const user = userEvent.setup();
      fetchMfaStatusMock.mockResolvedValue(MFA_ON);
      render(<MfaSettings onDisabled={vi.fn()} />);

      await user.type(await screen.findByLabelText(/password, to issue/i), "wrong");
      await user.click(screen.getByRole("button", { name: /issue new recovery/i }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/password is incorrect/i);
    });
  });

  describe("turning it off", () => {
    it("needs both a code and the password", async () => {
      const user = userEvent.setup();
      fetchMfaStatusMock.mockResolvedValue(MFA_ON);
      render(<MfaSettings onDisabled={vi.fn()} />);

      const button = await screen.findByRole("button", {
        name: /turn off two-factor/i,
      });
      // Neither alone is enough to act on.
      expect((button as HTMLButtonElement).disabled).toBe(true);

      await user.type(screen.getByLabelText(/current code or recovery/i), "123456");
      expect((button as HTMLButtonElement).disabled).toBe(true);

      await user.type(screen.getByLabelText(/^your password$/i), "correct-horse");
      expect((button as HTMLButtonElement).disabled).toBe(false);
    });

    it("sends both, and tells the app so it can sign out", async () => {
      // Disabling revokes every session, so the app has to be told rather than
      // left showing a dashboard whose cookies no longer work.
      const onDisabled = vi.fn();
      const user = userEvent.setup();
      fetchMfaStatusMock.mockResolvedValue(MFA_ON);
      render(<MfaSettings onDisabled={onDisabled} />);

      await user.type(await screen.findByLabelText(/current code or recovery/i), "123456");
      await user.type(screen.getByLabelText(/^your password$/i), "correct-horse");
      await user.click(screen.getByRole("button", { name: /turn off two-factor/i }));

      await waitFor(() =>
        expect(disableTotpMock).toHaveBeenCalledWith("123456", "correct-horse")
      );
      expect(onDisabled).toHaveBeenCalled();
    });

    it("warns that it signs out every device", async () => {
      fetchMfaStatusMock.mockResolvedValue(MFA_ON);
      render(<MfaSettings onDisabled={vi.fn()} />);

      expect(await screen.findByText(/signs out every device/i)).toBeTruthy();
    });

    it("reports a wrong code without signing out", async () => {
      disableTotpMock.mockRejectedValue({
        response: { status: 401, data: { msg: "That code is not valid." } },
      });
      const onDisabled = vi.fn();
      const user = userEvent.setup();
      fetchMfaStatusMock.mockResolvedValue(MFA_ON);
      render(<MfaSettings onDisabled={onDisabled} />);

      await user.type(await screen.findByLabelText(/current code or recovery/i), "000000");
      await user.type(screen.getByLabelText(/^your password$/i), "correct-horse");
      await user.click(screen.getByRole("button", { name: /turn off two-factor/i }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/not valid/i);
      expect(onDisabled).not.toHaveBeenCalled();
    });

    it("accepts a recovery code, for someone who has lost their phone", async () => {
      const user = userEvent.setup();
      fetchMfaStatusMock.mockResolvedValue(MFA_ON);
      render(<MfaSettings onDisabled={vi.fn()} />);

      const input = await screen.findByLabelText(/current code or recovery/i);
      // A recovery code is 16 characters, not 6, and must not be truncated.
      expect(input.getAttribute("maxlength")).toBeNull();
      const recoveryCode = RECOVERY_CODES[0]!;
      await user.type(input, recoveryCode);
      await user.type(screen.getByLabelText(/^your password$/i), "correct-horse");
      await user.click(screen.getByRole("button", { name: /turn off two-factor/i }));

      await waitFor(() =>
        expect(disableTotpMock).toHaveBeenCalledWith(recoveryCode, "correct-horse")
      );
    });
  });
});