/**
 * Shapes exchanged with the backend.
 *
 * This file is the single place the API's response shapes are described, so a
 * change to the backend that breaks a field becomes a type error rather than an
 * undefined at runtime.
 */

/** A row in GET /footprint/history. */
export interface FootprintEntry {
  id: number;
  car_km: number;
  electricity_kwh: number;
  meat_meals: number;
  plant_meals: number;
  total: number;
  region: string;
  factors_version: number;
  /** Present on newer rows; null for entries written before snapshots existed. */
  factors_applied: FactorSet | null;
  created_at: string | null;
}

/** The exact emission factors used to score one entry. */
export interface FactorSet {
  car_km: number;
  /** Recorded per row: a later update may turn a default into a measured value. */
  car_km_is_default?: boolean;
  electricity_kwh: number;
  meat_meal: number;
  plant_meal: number;
}

export interface HistoryResponse {
  entries: FootprintEntry[];
  total_entries: number;
  limit: number;
  offset: number;
}

export interface SummaryResponse {
  entries: number;
  total: number;
  average: number;
  breakdown: Record<string, number>;
  by_category: Record<string, number>;
  regions: string[];
  factors_versions: number[];
}

/** Where a factor came from, and what it measures. */
export interface Provenance {
  source: string;
  basis: string;
  year: number | null;
}

export interface RegionOption {
  code: string;
  label: string;
  electricity_kwh: number;
  /** kg CO2e per km for driving in this region. */
  car_km: number;
  /**
   * True when car_km is the documented global stand-in rather than a figure
   * measured for this region. Surfaced in the UI so a number is never presented
   * as more specific than it is.
   */
  car_km_is_default: boolean;
  provenance: {
    electricity_kwh: Provenance;
    car_km: Provenance;
    car_km_is_default: boolean;
    meat_meal: Provenance;
    plant_meal: Provenance;
  };
}

export interface FactorsCatalogue {
  default_region: string;
  factors_version: number;
  source: string;
  regions: RegionOption[];
  units: Record<string, string>;
}

/** Result of POST /footprint/calculate. */
export interface CalculateResult {
  id: number;
  total: number;
  breakdown: { car: number; electricity: number; meat: number; plant: number };
  inputs: Record<string, number>;
  region: string;
  travel_region?: string;
  factors_version: number;
  factors_applied: FactorSet;
  created_at: string | null;
}

export interface MeResponse {
  id: number;
  username: string;
  has_email: boolean;
  email_verified: boolean;
  /** Already masked by the backend. */
  email?: string;
  /** Whether a second factor is armed. Never carries the seed itself. */
  totp_enabled?: boolean;
  /** Unused single-use codes left, so the UI can warn before there are none. */
  recovery_codes_remaining?: number;
}

/**
 * A completed login.
 *
 * Deliberately does NOT carry optional mfa fields: the two shapes are separate
 * types (see MfaRequiredResponse) and Login branches on the union, so a missing
 * property can never be misread as a false one.
 */
export interface LoginResponse {
  msg: string;
  username: string;
  email_verified: boolean;
}

/**
 * The first half of a login, when a second factor is on.
 *
 * The password was correct but no session exists yet: the response carries a
 * pending token and no cookies. A client that ignored `mfa_required` would
 * believe it was signed in while holding nothing usable.
 */
export interface MfaRequiredResponse {
  msg: string;
  mfa_required: true;
  /** Expires in five minutes, and the server refuses it as a session token. */
  pending_token: string;
}

/** What POST /auth/mfa/start returns, to be scanned or typed into an app. */
export interface MfaSetupResponse {
  secret: string;
  /** otpauth:// URI. An authenticator app reads this from a QR code. */
  provisioning_uri: string;
  issuer: string;
  digits: number;
  period: number;
}

/** The 2FA state, for the settings panel. */
export interface MfaStatus {
  totp_enabled: boolean;
  recovery_codes_remaining: number;
  changed_at: string | null;
}

/** The second half of a login, once a code has been accepted. */
export interface MfaCheckResponse {
  msg: string;
  username: string;
  email_verified: boolean;
  /** "totp" or "recovery", so the UI can say the authenticator was not used. */
  second_factor: "totp" | "recovery";
}

export interface SessionRow {
  id: string;
  /** "Chrome on Windows" — browser and platform together. */
  label: string;
  browser: string;
  os: string | null;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string | null;
  last_seen_at: string | null;
  current: boolean;
  /** This address was not in use by this account before this session. */
  new_location: boolean;
  /** This browser was not used by this account before this session. */
  new_device: boolean;
  /** Either of the above: the one flag worth showing in the UI. */
  unrecognised: boolean;
}

export interface SessionsResponse {
  sessions: SessionRow[];
}

export interface ApiErrorBody {
  msg?: string;
  code?: string;
  detail?: string;
  errors?: Record<string, string>;
}
