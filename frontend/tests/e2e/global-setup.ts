import { execSync, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import url from "node:url";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..", "..", "..");

const SIDECAR_HOST = "127.0.0.1";
const SIDECAR_PORT = 18900;
const SIDECAR_TOKEN = "e2e-test-token";
const SIDECAR_BASE_URL = `http://${SIDECAR_HOST}:${SIDECAR_PORT}`;
const HEALTH_URL = `${SIDECAR_BASE_URL}/api/health`;
const MAX_HEALTH_RETRIES = 40;
const HEALTH_INTERVAL_MS = 500;

let sidecarProcess: ReturnType<typeof spawn> | null = null;
let dataDir = "";

async function globalSetup() {
  if (process.env.MEXEMPLAR_REAL_GRAND_TOUR === "1") {
    console.log("[e2e setup] Real Grand Tour uses its dedicated runtime; skipping default setup.");
    return;
  }

  // 0. 清理残留 sidecar 进程（Windows 上 taskkill 杀进程树）
  if (process.platform === "win32") {
    try {
      execSync(
        `for /f "tokens=5" %a in ('netstat -ano ^| findstr ":${SIDECAR_PORT}.*LISTENING"') do taskkill /PID %a /T /F`,
        { stdio: "ignore", shell: "cmd.exe" },
      );
    } catch {
      // 无残留进程
    }
  }

  // 1. 创建临时数据目录
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "mexemplar-e2e-"));
  process.env.EXEMPLAR_DATA_DIR = dataDir;
  console.log(`[e2e setup] 临时数据目录: ${dataDir}`);

  // 2. 先写种子数据（sidecar 启动前写入，确保 sidecar 打开 DB 时数据已存在）
  execSync(`uv run python frontend/tests/e2e/seed-data.py --data-dir "${dataDir}"`, {
    cwd: projectRoot,
    stdio: "inherit",
    env: { ...process.env, EXEMPLAR_DATA_DIR: dataDir },
  });
  console.log("[e2e setup] 种子数据写入完成");

  // 3. 启动 Python sidecar（此时 DB 已有种子数据）
  sidecarProcess = spawn(
    "uv",
    ["run", "python", "-m", "src.desktop_api", "--host", SIDECAR_HOST, "--port", String(SIDECAR_PORT), "--token", SIDECAR_TOKEN],
    {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, EXEMPLAR_DATA_DIR: dataDir },
      cwd: projectRoot,
    },
  );

  sidecarProcess.stdout?.on("data", (data: Buffer) => {
    process.stdout.write(`[sidecar stdout] ${data}`);
  });
  sidecarProcess.stderr?.on("data", (data: Buffer) => {
    process.stderr.write(`[sidecar stderr] ${data}`);
  });

  sidecarProcess.on("exit", (code) => {
    console.log(`[e2e setup] sidecar 进程退出，code=${code}`);
  });

  // 4. 轮询健康检查等待就绪
  console.log("[e2e setup] 等待 sidecar 就绪...");
  await waitForHealth();
  console.log("[e2e setup] sidecar 已就绪");

  // 5. 设置环境变量供 Vite 和测试使用
  process.env.VITE_MEXEMPLAR_API_BASE_URL = SIDECAR_BASE_URL;
  process.env.VITE_MEXEMPLAR_SESSION_TOKEN = SIDECAR_TOKEN;

  // 存储到文件供 teardown 使用
  const stateFile = path.join(os.tmpdir(), "mexemplar-e2e-state.json");
  fs.writeFileSync(stateFile, JSON.stringify({ dataDir, pid: sidecarProcess.pid, port: SIDECAR_PORT, token: SIDECAR_TOKEN }));
  console.log(`[e2e setup] 状态文件: ${stateFile}`);
}

async function waitForHealth(): Promise<void> {
  for (let i = 0; i < MAX_HEALTH_RETRIES; i++) {
    try {
      const response = await fetch(HEALTH_URL, {
        headers: { "X-Mexemplar-Session": SIDECAR_TOKEN },
        signal: AbortSignal.timeout(2000),
      });
      if (response.ok) return;
    } catch {
      // 还没就绪，继续等
    }
    await new Promise((resolve) => setTimeout(resolve, HEALTH_INTERVAL_MS));
  }
  throw new Error(`sidecar 在 ${(MAX_HEALTH_RETRIES * HEALTH_INTERVAL_MS) / 1000}s 内未就绪`);
}

export default globalSetup;
