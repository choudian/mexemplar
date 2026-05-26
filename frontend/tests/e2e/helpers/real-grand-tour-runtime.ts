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
    maxPaidCalls: boundedPositiveInteger(env.MEXEMPLAR_REAL_GRAND_TOUR_MAX_PAID_CALLS, 30, 30),
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
  const port = await allocateLocalPort();
  const token = crypto.randomBytes(24).toString("base64url");
  const baseUrl = `http://127.0.0.1:${port}`;
  let child: ChildProcess | null = null;

  if (options.spawnSidecar !== false) {
    child = spawn(
      "uv",
      ["run", "python", "-m", "src.desktop_api", "--host", "127.0.0.1", "--port", String(port)],
      {
        cwd: options.projectRoot,
        stdio: ["ignore", "pipe", "pipe"],
        env: {
          ...process.env,
          EXEMPLAR_DATA_DIR: dataDir,
          MEXEMPLAR_DESKTOP_TOKEN: token,
          MEXEMPLAR_REAL_GRAND_TOUR: "1",
          MEXEMPLAR_REAL_GRAND_TOUR_AUDIT_FILE: auditFile,
          MEXEMPLAR_REAL_GRAND_TOUR_MAX_MINUTES: String(config.maxElapsedMinutes),
          MEXEMPLAR_REAL_GRAND_TOUR_MAX_PAID_CALLS: String(config.maxPaidCalls),
        },
      },
    );
    child.stdout?.resume();
    child.stderr?.resume();
  }

  return {
    status: "started",
    runtime: {
      baseUrl,
      dataDir,
      auditFile,
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
  timeoutMs = 30_000,
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
      ok = false;
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
