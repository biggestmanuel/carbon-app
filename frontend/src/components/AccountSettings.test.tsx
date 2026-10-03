/**
 * Data export and account deletion.
 *
 * Deletion is the one irreversible action in the app, so the tests concentrate on
 * the guards: nothing happens until the password is typed and DELETE is spelled
 * out, and the password really is sent.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { apiMock, resetApiMocks } from "../test/api-mock";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: apiMock };
});

import AccountSettings from "./AccountSettings";

/** jsdom has no object URL support for downloads. */
function stubObjectUrl() {
  const created: Blob[] = [];
  const revoked: string[] = [];
  const fakeUrls: string[] = [];

  URL.createObjectURL = vi.fn((blob: Blob) => {
    created.push(blob);
    const url = `blob:mock/${created.length}`;
    fakeUrls.push(url);
    return url;
  });
  URL.revokeObjectURL = vi.fn((url: string) => revoked.push(url));

  return { created, revoked, fakeUrls };
}

async function armDeletion(user: ReturnType<typeof userEvent.setup>, password: string) {
  await user.type(screen.getByLabelText(/confirm with your password/i), password);
  await user.type(screen.getByLabelText(/type delete to enable/i), "DELETE");
}

beforeEach(() => {
  resetApiMocks();
  apiMock.get.mockResolvedValue({ data: "blob" });
  apiMock.delete.mockResolvedValue({ data: { msg: "Account deleted" } });
});

describe("AccountSettings export", () => {
  it("offers both formats", () => {
    render(<AccountSettings onDeleted={vi.fn()} />);

    expect(screen.getByRole("button", { name: /export as json/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /export as csv/i })).toBeTruthy();
  });

  it("requests a CSV export and cleans up the object URL", async () => {
    const { revoked } = stubObjectUrl();
    const user = userEvent.setup();
    render(<AccountSettings onDeleted={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /export as csv/i }));

    await waitFor(() =>
      expect(apiMock.get).toHaveBeenCalledWith("/account/export?format=csv", {
        responseType: "blob",
      })
    );
    expect(await screen.findByRole("status")).toHaveTextContent(/CSV export is downloading/i);
    // A leaked object URL pins the whole response in memory for the page's life.
    expect(revoked).toHaveLength(1);
  });

  it("reports a failed export", async () => {
    stubObjectUrl();
    apiMock.get.mockRejectedValue({ response: { status: 500, data: { msg: "Boom" } } });
    const user = userEvent.setup();
    render(<AccountSettings onDeleted={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /export as json/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/i);
  });
});

describe("AccountSettings deletion", () => {
  it("keeps the delete button disabled until DELETE is typed", async () => {
    const user = userEvent.setup();
    render(<AccountSettings onDeleted={vi.fn()} />);

    const button = screen.getByRole("button", { name: /delete my account/i });
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText(/confirm with your password/i), "correct-horse");
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText(/type delete to enable/i), "DELETE");
    expect(button).toBeEnabled();
  });

  it("is case-insensitive about the confirmation word", async () => {
    const user = userEvent.setup();
    render(<AccountSettings onDeleted={vi.fn()} />);

    await armDeletion(user, "correct-horse");
    expect(screen.getByRole("button", { name: /delete my account/i })).toBeEnabled();
  });

  it("sends the password again and reports the result", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    render(<AccountSettings onDeleted={onDeleted} />);

    await armDeletion(user, "correct-horse");
    await user.click(screen.getByRole("button", { name: /delete my account/i }));

    // The whole point of re-asking: a stolen session cookie must not be enough.
    await waitFor(() =>
      expect(apiMock.delete).toHaveBeenCalledWith("/account/account", {
        data: { password: "correct-horse" },
      })
    );
    expect(onDeleted).toHaveBeenCalled();
  });

  it("stays put when the password is wrong", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    apiMock.delete.mockRejectedValue({
      response: { status: 403, data: { msg: "Password is incorrect" } },
    });
    render(<AccountSettings onDeleted={onDeleted} />);

    await armDeletion(user, "guess-the-password");
    await user.click(screen.getByRole("button", { name: /delete my account/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/password is incorrect/i);
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("masks the confirmation password field", () => {
    render(<AccountSettings onDeleted={vi.fn()} />);

    expect(screen.getByLabelText(/confirm with your password/i)).toHaveAttribute(
      "type",
      "password"
    );
  });
});
