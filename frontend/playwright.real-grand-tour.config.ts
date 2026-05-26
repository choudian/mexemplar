import { defineConfig, devices } from "@playwright/test";

import { readRealGrandTourConfig } from "./tests/e2e/helpers/real-grand-tour-runtime";

const port = Number(process.env.PLAYWRIGHT_REAL_GRAND_TOUR_DEV_SERVER_PORT ?? "5175");
const baseURL = `http://127.0.0.1:${port}`;
const maxRunMs = readRealGrandTourConfig().maxElapsedMinutes * 60 * 1000;
const noProxyHosts = ["127.0.0.1", "localhost", "::1"];
const currentNoProxy = process.env.NO_PROXY ?? process.env.no_proxy ?? "";
const noProxy = Array.from(
  new Set([...currentNoProxy.split(",").filter(Boolean), ...noProxyHosts]),
).join(",");
process.env.NO_PROXY = noProxy;
process.env.no_proxy = noProxy;

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: ["grand-tour.real.spec.ts"],
  globalTimeout: maxRunMs + 120_000,
  timeout: maxRunMs,
  expect: { timeout: 30_000 },
  workers: 1,
  fullyParallel: false,
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    headless: false,
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      VITE_MEXEMPLAR_API_BASE_URL: process.env.MEXEMPLAR_REAL_GRAND_TOUR_BASE_URL ?? "",
      VITE_MEXEMPLAR_SESSION_TOKEN: process.env.MEXEMPLAR_REAL_GRAND_TOUR_TOKEN ?? "",
    },
  },
});
