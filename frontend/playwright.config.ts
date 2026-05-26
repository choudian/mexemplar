import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

function localChromiumExecutable(): string | undefined {
  const root = process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "ms-playwright") : "";
  if (!root || !fs.existsSync(root)) return undefined;
  const candidates = fs
    .readdirSync(root)
    .filter((name) => name.startsWith("chromium_headless_shell-"))
    .sort()
    .reverse()
    .map((name) => path.join(root, name, "chrome-headless-shell-win64", "chrome-headless-shell.exe"));
  return candidates.find((candidate) => fs.existsSync(candidate));
}

const isHeaded = process.argv.some((a) => a === "--headed") || process.env.PLAYWRIGHT_HEADED === "1";
if (isHeaded) process.env.PLAYWRIGHT_HEADED = "1";
if (isHeaded && !process.env.GRAND_TOUR_DELAY) process.env.GRAND_TOUR_DELAY = "1200";
const executablePath =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ?? (isHeaded ? undefined : localChromiumExecutable());
const port = Number(process.env.PLAYWRIGHT_DEV_SERVER_PORT ?? "5174");
const baseURL = `http://127.0.0.1:${port}`;
const noProxyHosts = ["127.0.0.1", "localhost", "::1"];
const currentNoProxy = process.env.NO_PROXY ?? process.env.no_proxy ?? "";
const noProxy = Array.from(new Set([...currentNoProxy.split(",").filter(Boolean), ...noProxyHosts])).join(",");
process.env.NO_PROXY = noProxy;
process.env.no_proxy = noProxy;

export default defineConfig({
  testDir: "tests/e2e",
  testIgnore: ["grand-tour.real.spec.ts"],
  timeout: 180_000,
  expect: { timeout: 15_000 },
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    headless: !isHeaded,
    launchOptions: executablePath ? { executablePath } : undefined,
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
