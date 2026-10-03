import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", "dist/**"],
    // Process CSS so layout assertions can read real computed styles. Without
    // this jsdom returns defaults and every getComputedStyle check passes
    // vacuously.
    css: true,
    // The fork pool ran this suite out of memory on Windows (worker exit 134).
    // A single thread keeps the footprint flat.
    pool: "threads",
    maxWorkers: 1,
    minWorkers: 1,
  },
});