import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

async function globalTeardown() {
  const stateFile = path.join(os.tmpdir(), "mexemplar-e2e-state.json");

  if (!fs.existsSync(stateFile)) {
    console.log("[e2e teardown] 无状态文件，跳过清理");
    return;
  }

  const state = JSON.parse(fs.readFileSync(stateFile, "utf-8"));
  const { dataDir, pid, port } = state;

  // 终止 sidecar 进程（Windows 兼容：用 taskkill 杀进程树）
  if (pid) {
    try {
      if (process.platform === "win32") {
        execSync(`taskkill /PID ${pid} /T /F`, { stdio: "ignore" });
      } else {
        process.kill(pid, "SIGTERM");
      }
      console.log(`[e2e teardown] 已终止 sidecar (pid=${pid})`);
    } catch {
      // 进程可能已退出
    }
  }

  // 等待端口释放
  await new Promise((resolve) => setTimeout(resolve, 1000));

  // 删除临时数据目录
  if (dataDir && fs.existsSync(dataDir)) {
    try {
      fs.rmSync(dataDir, { recursive: true, force: true });
      console.log(`[e2e teardown] 已删除临时数据目录: ${dataDir}`);
    } catch (err) {
      console.warn(`[e2e teardown] 删除临时目录失败: ${err}`);
    }
  }

  // 清理状态文件
  fs.unlinkSync(stateFile);
  console.log("[e2e teardown] 清理完成");
}

export default globalTeardown;
