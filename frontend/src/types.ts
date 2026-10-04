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
}

export interface LoginResponse {
  msg: string;
  username: string;
  email_verified: boolean;
}

export interface SessionRow {
  id: string;
  label: string;
  user_agent: string | null;
  ip_address: string | null;
  created_at: string | null;
  last_seen_at: string | null;
  current: boolean;
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
