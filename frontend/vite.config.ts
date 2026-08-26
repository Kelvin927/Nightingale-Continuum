import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const runtimeEnvironment = (
  globalThis as typeof globalThis & {
    process?: { env: Record<string, string | undefined> };
  }
).process?.env;
const apiTarget = runtimeEnvironment?.VITE_API_TARGET ?? "http://127.0.0.1:8000";
const devPort = Number(runtimeEnvironment?.VITE_DEV_PORT ?? "5173");

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: devPort,
    strictPort: true,
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget,
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/App.tsx", "src/api.ts", "src/components/**/*.tsx"],
      exclude: ["src/**/*.test.{ts,tsx}"],
      reporter: ["text", "json", "json-summary"],
      reportsDirectory: "../output/evidence/frontend-coverage",
      reportOnFailure: true,
      thresholds: {
        statements: 100,
        branches: 100,
        functions: 100,
        lines: 100,
      },
    },
  },
});
