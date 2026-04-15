"""
mitmproxy CA 证书管理工具。

负责检测并安装 mitmproxy 自签 CA 证书到系统根信任区。
证书文件统一存放在 data/ 目录下。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MITMPROXY_CERT_SUBJECT = "mitmproxy"
# mitmdump 默认生成证书的位置
MITMPROXY_DEFAULT_CERT = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer"


def _get_default_cert_path() -> Path:
    """返回默认证书路径，不触发目录创建。"""
    project_root = Path(__file__).parent.parent.parent
    return project_root / "data" / "mitmproxy-ca-cert.cer"


DEFAULT_CERT_PATH = _get_default_cert_path()


class CertManager:
    """检测并安装 mitmproxy CA 证书。"""

    def __init__(self, cert_path: Optional[Path] = None) -> None:
        self.cert_path = cert_path or DEFAULT_CERT_PATH

    def is_installed(self) -> bool:
        """检查 mitmproxy CA 证书是否已在系统信任区。"""
        try:
            result = subprocess.run(
                ["certutil", "-store", "Root"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return MITMPROXY_CERT_SUBJECT.lower() in result.stdout.lower()
        except Exception as exc:
            logger.warning(f"[CertManager] 检测证书失败: {exc}")
            return False

    def _ensure_cert_file(self) -> bool:
        """确保证书文件存在。先检查 data 目录，再检查 ~/.mitmproxy，都没有则生成。"""
        if self.cert_path.exists():
            return True
        self.cert_path.parent.mkdir(parents=True, exist_ok=True)

        # ~/.mitmproxy 已有证书，直接复制到 data 目录
        if MITMPROXY_DEFAULT_CERT.exists():
            shutil.copy2(MITMPROXY_DEFAULT_CERT, self.cert_path)
            logger.info(f"[CertManager] 从 ~/.mitmproxy 复制证书到 {self.cert_path}")
            return True

        # 启动 mitmdump 生成证书
        logger.info("[CertManager] 证书文件不存在，启动 mitmdump 生成...")
        try:
            proc = subprocess.Popen(
                ["mitmdump", "-w", "NUL"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            # mitmdump 启动时即生成 CA 证书，等文件出现即可关闭
            for _ in range(50):  # 最多等 5 秒
                time.sleep(0.1)
                if MITMPROXY_DEFAULT_CERT.exists():
                    break

            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

            if MITMPROXY_DEFAULT_CERT.exists():
                shutil.copy2(MITMPROXY_DEFAULT_CERT, self.cert_path)
                logger.info(f"[CertManager] 证书已生成并复制到 {self.cert_path}")
                return True

            logger.error("[CertManager] mitmdump 运行后仍未生成证书")
            return False
        except FileNotFoundError:
            logger.error("[CertManager] mitmdump 未安装，请先安装 mitmproxy")
            return False
        except Exception as exc:
            logger.error(f"[CertManager] 生成证书失败: {exc}")
            return False

    def install(self) -> bool:
        """安装证书到系统根信任区。"""
        if not self.cert_path.exists():
            if not self._ensure_cert_file():
                return False

        try:
            result = subprocess.run(
                ["certutil", "-addstore", "Root", str(self.cert_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                logger.info("[CertManager] 证书安装成功")
                return True

            logger.error(
                f"[CertManager] 证书安装失败 (exit={result.returncode}): "
                f"{result.stdout.strip() or result.stderr.strip()}"
            )
            return False
        except Exception as exc:
            logger.error(f"[CertManager] 安装证书异常: {exc}")
            return False

    def ensure_installed(self) -> bool:
        """确保证书已安装。"""
        if self.is_installed():
            logger.info("[CertManager] 证书已安装，无需重复安装")
            return True
        logger.info("[CertManager] 证书未安装，尝试安装")
        return self.install()
