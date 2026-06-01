import { spawn, type ChildProcess } from "node:child_process";
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

export interface RealGrandTourConfig {
  optIn: boolean;
  allowLiveCapture: boolean;
  maxElapsedMinutes: number;
  maxPaidCalls: number;
}

export interface RealGrandTourRuntime {
  baseUrl: string;
  dataDir: string;
  auditFile: string;
  stdoutLogFile: string;
  stderrLogFile: string;
  port: number;
  token: string;
  process: ChildProcess | null;
  cleanup: () => Promise<"completed" | "failed">;
}

export interface RealGrandTourStartResult {
  status: "started" | "skipped";
  reason?: string;
  runtime?: RealGrandTourRuntime;
}

export interface RealGrandTourAuditSnapshot {
  paidCallCount: number;
  credentialMutationCount: number;
  budgetExceeded: boolean;
}

export interface RealGrandTourCleanupDeps {
  platform?: NodeJS.Platform;
  execFileSync?: typeof execFileSync;
  rmSync?: typeof fs.rmSync;
}

export function readRealGrandTourConfig(env: NodeJS.ProcessEnv = process.env): RealGrandTourConfig {
  return {
    optIn: env.MEXEMPLAR_REAL_GRAND_TOUR === "1",
    allowLiveCapture: env.MEXEMPLAR_ALLOW_LIVE_CAPTURE === "1",
    maxElapsedMinutes: boundedPositiveInteger(env.MEXEMPLAR_REAL_GRAND_TOUR_MAX_MINUTES, 20, 20),
    maxPaidCalls: boundedPositiveInteger(env.MEXEMPLAR_REAL_GRAND_TOUR_MAX_PAID_CALLS, 50, 50),
  };
}

export function realGrandTourSkipReason(config: RealGrandTourConfig): string | null {
  if (!config.optIn) return "real_tour_opt_in_missing";
  if (config.maxElapsedMinutes <= 0 || config.maxPaidCalls <= 0) return "invalid_budget";
  return null;
}

export async function allocateLocalPort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
    server.on("error", reject);
  });
}

export async function startRealGrandTourRuntime(
  options: {
    projectRoot: string;
    config?: RealGrandTourConfig;
    spawnSidecar?: boolean;
  },
): Promise<RealGrandTourStartResult> {
  const config = options.config ?? readRealGrandTourConfig();
  const skipReason = realGrandTourSkipReason(config);
  if (skipReason) return { status: "skipped", reason: skipReason };

  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "mexemplar-real-gt-"));
  const auditFile = path.join(dataDir, "real-grand-tour-audit.json");
  const logDir = path.resolve(process.cwd(), "test-results", "real-grand-tour");
  fs.mkdirSync(logDir, { recursive: true });
  const runtimeLogId = path.basename(dataDir);
  const stdoutLogFile = path.join(logDir, `${runtimeLogId}.sidecar.stdout.log`);
  const stderrLogFile = path.join(logDir, `${runtimeLogId}.sidecar.stderr.log`);
  fs.writeFileSync(stdoutLogFile, "", "utf-8");
  fs.writeFileSync(stderrLogFile, "", "utf-8");
  const envPort = Number(process.env.MEXEMPLAR_REAL_GRAND_TOUR_PORT);
  const envBaseUrl = process.env.MEXEMPLAR_REAL_GRAND_TOUR_BASE_URL ?? "";
  const useExternalSidecar = envBaseUrl.trim() !== "";
  const port = useExternalSidecar ? 0 : (Number.isInteger(envPort) && envPort > 0 ? envPort : await allocateLocalPort());
  const token = process.env.MEXEMPLAR_REAL_GRAND_TOUR_TOKEN ?? crypto.randomBytes(24).toString("base64url");
  const baseUrl = useExternalSidecar ? envBaseUrl : `http://127.0.0.1:${port}`;
  const frontendPort = Number(process.env.PLAYWRIGHT_REAL_GRAND_TOUR_DEV_SERVER_PORT ?? "5175");
  const safeFixtureUrl = `http://127.0.0.1:${frontendPort}/real-grand-tour-safe-fixture.html`;
  const verboseLogs = process.env.MEXEMPLAR_REAL_GRAND_TOUR_VERBOSE_LOGS === "1";
  let child: ChildProcess | null = null;

  if (options.spawnSidecar !== false && !useExternalSidecar) {
    child = spawn(
      "uv",
      [
        "run",
        "python",
        "-m",
        "src.desktop_api",
        "--host",
        "127.0.0.1",
        "--port",
        String(port),
        ...(verboseLogs ? ["--verbose"] : []),
      ],
      {
        cwd: options.projectRoot,
        stdio: ["ignore", "pipe", "pipe"],
        env: {
          ...process.env,
          EXEMPLAR_DATA_DIR: dataDir,
          MEXEMPLAR_DESKTOP_TOKEN: token,
          PYTHONIOENCODING: "utf-8",
          PYTHONUTF8: "1",
          MEXEMPLAR_REAL_GRAND_TOUR: "1",
          MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE: auditFile,
          MEXEMPLAR_REAL_GRAND_TOUR_MAX_MINUTES: String(config.maxElapsedMinutes),
          MEXEMPLAR_REAL_GRAND_TOUR_MAX_PAID_CALLS: String(config.maxPaidCalls),
          MEXEMPLAR_REAL_GRAND_TOUR_AUTOMATE_BROWSER_JOURNEY: "1",
          MEXEMPLAR_REAL_GRAND_TOUR_FIXTURE_URL: safeFixtureUrl,
          MEXEMPLAR_REAL_GRAND_TOUR_FIXED_INPUT: "Sample approval request for local validation only",
        },
      },
    );
    child.stdout?.pipe(fs.createWriteStream(stdoutLogFile, { flags: "a" }));
    child.stderr?.pipe(fs.createWriteStream(stderrLogFile, { flags: "a" }));
  }

  return {
    status: "started",
    runtime: {
      baseUrl,
      dataDir,
      auditFile,
      stdoutLogFile,
      stderrLogFile,
      port,
      token,
      process: child,
      cleanup: async () => cleanupRealGrandTourRuntime(child, dataDir),
    },
  };
}

export function readRealGrandTourAudit(dataDir: string): RealGrandTourAuditSnapshot {
  const auditFile = path.join(dataDir, "real-grand-tour-audit.json");
  try {
    const raw = fs.readFileSync(auditFile, "utf-8");
    const parsed = JSON.parse(raw) as Partial<RealGrandTourAuditSnapshot>;
    const paidCallCount = Number(parsed.paidCallCount);
    const credentialMutationCount = Number(parsed.credentialMutationCount);
    if (
      !Number.isInteger(paidCallCount) || paidCallCount < 0 ||
      !Number.isInteger(credentialMutationCount) || credentialMutationCount < 0 ||
      typeof parsed.budgetExceeded !== "boolean"
    ) {
      throw new Error("invalid_audit_payload");
    }
    return {
      paidCallCount,
      credentialMutationCount,
      budgetExceeded: parsed.budgetExceeded,
    };
  } catch {
    throw new Error("real_tour_audit_unavailable");
  }
}

export async function waitForRealGrandTourHealth(
  runtime: Pick<RealGrandTourRuntime, "baseUrl" | "token">,
  timeoutMs = 120_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${runtime.baseUrl}/api/health`, {
        headers: { "X-Mexemplar-Session": runtime.token },
        signal: AbortSignal.timeout(2000),
      });
      if (response.ok) return;
    } catch {
      // Sidecar is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("real_tour_sidecar_not_ready");
}

export async function cleanupRealGrandTourRuntime(
  child: ChildProcess | null,
  dataDir: string,
  deps: RealGrandTourCleanupDeps = {},
): Promise<"completed" | "failed"> {
  let ok = true;
  const platform = deps.platform ?? process.platform;
  const exec = deps.execFileSync ?? execFileSync;
  const rm = deps.rmSync ?? fs.rmSync;
  if (child?.pid) {
    try {
      if (platform === "win32") {
        exec("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      } else {
        child.kill("SIGTERM");
      }
    } catch {
      const childAlreadyExited =
        child.exitCode !== null && child.exitCode !== undefined ||
        child.signalCode !== null && child.signalCode !== undefined;
      if (!childAlreadyExited) {
        ok = false;
      }
    }
  }
  try {
    rm(dataDir, { recursive: true, force: true });
  } catch {
    ok = false;
  }
  return ok ? "completed" : "failed";
}

function boundedPositiveInteger(value: string | undefined, fallback: number, ceiling: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? Math.min(parsed, ceiling) : fallback;
}
