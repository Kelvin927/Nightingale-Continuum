import { tmpdir } from "node:os";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

const e2eDatabaseUrl = `sqlite:///${join(tmpdir(), `nightingale-e2e-${process.pid}.sqlite3`)}`;
const e2eApiPort = Number(process.env.NIGHTINGALE_E2E_API_PORT ?? "18000");
const e2eWebPort = Number(process.env.NIGHTINGALE_E2E_WEB_PORT ?? "18001");
const e2eApiUrl = `http://127.0.0.1:${e2eApiPort}`;
const e2eWebUrl = `http://127.0.0.1:${e2eWebPort}`;
const e2ePython = process.env.NIGHTINGALE_E2E_PYTHON ?? "../.venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 1,
  reporter: [
    ["list"],
    ["json", { outputFile: "../output/evidence/browser_e2e.json" }],
    ["html", { open: "never" }],
  ],
  use: {
    baseURL: e2eWebUrl,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      grepInvert: /@mobile/,
      use: { ...devices["Desktop Chrome"] },
    },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: `NIGHTINGALE_DATABASE_URL='${e2eDatabaseUrl}' PYTHONPATH=../backend '${e2ePython}' -m uvicorn app.main:app --host 127.0.0.1 --port ${e2eApiPort}`,
      cwd: ".",
      url: `${e2eApiUrl}/health`,
      reuseExistingServer: false,
    },
    {
      command: `VITE_API_TARGET='${e2eApiUrl}' VITE_DEV_PORT='${e2eWebPort}' npm run dev -- --host 127.0.0.1 --strictPort`,
      cwd: ".",
      url: e2eWebUrl,
      reuseExistingServer: false,
    },
  ],
});
