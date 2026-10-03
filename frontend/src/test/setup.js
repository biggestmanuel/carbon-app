import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// The API base URL is read from import.meta.env at module load. Pin it so
// tests never depend on a developer's local .env.
process.env.VITE_API_URL = "http://localhost:5000";