/**
 * A typed stand-in for the api module.
 *
 * vi.mock replaces `api` with a bare object, which TypeScript cannot see through
 * to know that `api.get` is a mock. Importing the mocks from here instead of
 * from "./api" keeps `.mockResolvedValue` and friends type-checked.
 */
import { vi } from "vitest";
import type { Mock } from "vitest";
import type {
  FactorsCatalogue,
  MeResponse,
  MfaCheckResponse,
  MfaSetupResponse,
  MfaStatus,
  RegionOption,
} from "../types";

export type ApiMock = {
  get: Mock;
  post: Mock;
  delete: Mock;
  put: Mock;
  patch: Mock;
};

export const apiMock: ApiMock = {
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
};

export const fetchSessionMock: Mock = vi.fn();
export const setSessionExpiredHandlerMock: Mock = vi.fn();

/** Resolve every call with `data`, so a child component never crashes on undefined. */
export function resolveAllWith(data: unknown = {}) {
  const resolved = () => Promise.resolve({ data });
  for (const method of Object.values(apiMock)) {
    method.mockReset();
    method.mockImplementation(resolved);
  }
}

export function resetApiMocks(): void {
  for (const method of Object.values(apiMock)) method.mockReset();
  fetchSessionMock.mockReset();
}

/** Calls made to one URL, in order. Keeps assertions readable. */
export function callsTo(url: string): unknown[][] {
  return apiMock.get.mock.calls.filter((call) => call[0] === url) as unknown[][];
}

export const ALICE: MeResponse = {
  id: 1,
  username: "alice",
  has_email: true,
  email_verified: false,
  email: "a***e@example.com",
};

/** What /auth/mfa/start returns: a secret to scan or type into an app. */
export const MFA_SETUP = {
  secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
  provisioning_uri:
    "otpauth://totp/carbon-app%3Aalice?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP" +
    "&issuer=carbon-app&algorithm=SHA1&digits=6&period=30",
  issuer: "carbon-app",
  digits: 6,
  period: 30,
};

/** Stand-in recovery codes. Only ever shown once, so they live in the fixture. */
export const RECOVERY_CODES = [
  "A2B3C4D5E6F7G8H9",
  "J9K8L7M6N5O4P3Q2",
  "R1S2T3U4V5W6X7Y8",
];

/**
 * The second-factor calls, mocked by name.
 *
 * These are named exports in api.ts that close over the axios instance, so
 * replacing the instance in a test would not intercept them -- the component
 * would call the live transport.
 */
export const verifySecondFactorMock = vi.fn<
  (pendingToken: string, code: string) => Promise<MfaCheckResponse>
>();
export const startTotpSetupMock = vi.fn<() => Promise<MfaSetupResponse>>();
export const confirmTotpSetupMock =
  vi.fn<(secret: string, code: string) => Promise<{ msg: string; recovery_codes: string[] }>>();
export const fetchMfaStatusMock = vi.fn<() => Promise<MfaStatus>>();
export const disableTotpMock = vi.fn<(code: string, password: string) => Promise<void>>();
export const regenerateRecoveryCodesMock = vi.fn<(password: string) => Promise<string[]>>();

/** Put every 2FA mock back to a rejecting default between tests. */
export function resetMfaMocks() {
  verifySecondFactorMock.mockReset();
  startTotpSetupMock.mockReset();
  confirmTotpSetupMock.mockReset();
  fetchMfaStatusMock.mockReset();
  disableTotpMock.mockReset();
  regenerateRecoveryCodesMock.mockReset();

  fetchMfaStatusMock.mockResolvedValue(MFA_OFF);
  startTotpSetupMock.mockResolvedValue(MFA_SETUP);
  confirmTotpSetupMock.mockResolvedValue({ msg: "Two-factor authentication is on.", recovery_codes: RECOVERY_CODES });
  verifySecondFactorMock.mockResolvedValue({
    msg: "Logged in",
    username: "alice",
    email_verified: true,
    second_factor: "totp",
  });
  regenerateRecoveryCodesMock.mockResolvedValue(RECOVERY_CODES);
}

/** The 2FA state, as /auth/mfa/status reports it. */
export const MFA_ON: MfaStatus = {
  totp_enabled: true,
  recovery_codes_remaining: 10,
  changed_at: "2026-03-01T09:00:00+00:00",
};

export const MFA_OFF: MfaStatus = {
  totp_enabled: false,
  recovery_codes_remaining: 0,
  changed_at: null,
};

/**
 * A factor catalogue for tests.
 *
 * Every region needs the full RegionOption shape including provenance, which is
 * a lot to repeat. `carFactors` is the part that matters: it decides which
 * travel regions the form will offer, since a region whose car factor matches
 * home's is not worth putting on screen.
 */
export function makeFactorsCatalogue(options?: {
  defaultRegion?: string;
  factorsVersion?: number;
  /** code -> kg CO2e per km. Regions not listed get the shared default. */
  carFactors?: Record<string, number>;
  /** code -> kg CO2e per kWh. */
  electricityFactors?: Record<string, number>;
}): FactorsCatalogue {
  const carFactors = options?.carFactors ?? {};
  const electricityFactors = options?.electricityFactors ?? DEFAULT_ELECTRICITY;
  const defaultCar = carFactors["world"] ?? 0.16984;

  const prov = (source: string, basis: string, year: number | null) => ({
    source,
    basis,
    year,
  });

  const codes = ["world", "us", "eu", "gb", "fr", "de", "in", "ca", "au", "br"] as const;
  const regions: RegionOption[] = codes.map((code) => {
    const hasOwnCar = Object.prototype.hasOwnProperty.call(carFactors, code);
    return {
      code,
      label: code.toUpperCase(),
      electricity_kwh: electricityFactors[code] ?? 0.475,
      car_km: hasOwnCar ? carFactors[code] ?? defaultCar : defaultCar,
      car_km_is_default: !hasOwnCar,
      provenance: {
        electricity_kwh: prov("test grid", "annual average mix", null),
        car_km: hasOwnCar
          ? prov("test measured car figure", "fleet average", 2024)
          : prov("test global default", "fleet average", 2024),
        car_km_is_default: !hasOwnCar,
        meat_meal: prov("Poore & Nemecek (2018)", "global median per meal", 2018),
        plant_meal: prov("Poore & Nemecek (2018)", "global median per meal", 2018),
      },
    };
  });

  return {
    default_region: options?.defaultRegion ?? "world",
    factors_version: options?.factorsVersion ?? 3,
    source: "static-reference",
    regions,
    units: {},
  };
}

/** Distinct per region, so selecting one changes the displayed factor. */
const DEFAULT_ELECTRICITY: Record<string, number> = {
  world: 0.475,
  us: 0.372,
  eu: 0.275,
  gb: 0.207,
  fr: 0.056,
  de: 0.349,
  in: 0.713,
  ca: 0.127,
  au: 0.517,
  br: 0.088,
};
