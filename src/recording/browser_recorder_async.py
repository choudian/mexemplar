# ⚠️ 备用实现：异步浏览器录制器
# 本文件是解决特定 BUG 的备用方案
#
# 背景：
# - 之前某些问题（如新标签页问题）通过异步 API 解决
# - 当前主录制器 (browser_recorder.py) 使用同步版本
# - 如果同步版本出现问题，可以切换到此异步版本
#
# 状态：未使用，保留作为备选方案
# 待测试：完成调整后需要测试此版本是否仍有优势

"""
简化版异步浏览器录制器

使用 Playwright 异步 API + 持久化上下文，解决新标签页问题

用法：
    recorder = AsyncBrowserRecorder()
    await recorder.start_recording("https://www.baidu.com")
    # ... 用户操作
    session = await recorder.stop_recording()
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


class AsyncBrowserRecorder:
    """
    简化版异步浏览器录制器

    使用异步 API + 持久化上下文，解决新标签页问题并加载扩展
    """

    def __init__(self):
        self._playwright = None  # Playwright API 对象（不是上下文管理器）
        self._playwright_context = None  # 上下文管理器
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._is_recording = False

    def _get_extension_path(self) -> Path:
        """获取浏览器扩展路径"""
        # 获取项目根目录
        project_root = Path(__file__).parent.parent.parent
        extension_path = project_root / "src" / "recording" / "browser_extension"

        if not extension_path.exists():
            raise FileNotFoundError(f"扩展目录不存在: {extension_path}")

        return extension_path

    async def start_recording(self, start_url: str = "https://www.baidu.com"):
        """
        启动浏览器并开始录制（异步版本 + 持久化上下文）

        Args:
            start_url: 起始 URL
        """
        logger.info("启动异步浏览器录制器（持久化模式 + 扩展）...")

        # ⭐ 使用 async with 正确启动 Playwright
        self._playwright_context = async_playwright()
        self._playwright = await self._playwright_context.__aenter__()

        # 获取扩展路径
        extension_path = self._get_extension_path()
        logger.info(f"扩展路径: {extension_path}")

        # 使用持久化上下文（可以加载扩展）
        user_data_dir = Path("./data/playwright_async_test")
        user_data_dir.mkdir(parents=True, exist_ok=True)

        logger.info("正在启动浏览器（持久化模式 + 异步 API）...")

        # 转换扩展路径为正斜杠（Windows 兼容）
        extension_path_str = extension_path.as_posix()

        # 启动持久化上下文
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            accept_downloads=True,
            ignore_default_args=["--enable-automation"],
            args=[
                f"--disable-extensions-except={extension_path_str}",
                f"--load-extension={extension_path_str}",
                "--disable-gpu",
                "--no-sandbox",
            ],
        )

        logger.info("✅ 浏览器已启动（持久化模式 + 扩展已加载）")

        # ⭐ 注册新页面监听器（验证异步 API 能否检测新标签页）
        page_count = [0]

        def on_page(page):
            page_count[0] += 1
            logger.info(f"✅ [新页面 #{page_count[0]}] 检测到: {page.url}")

            # 异步等待页面加载
            async def wait_load():
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    logger.info(f"   页面 #{page_count[0]} 加载完成: {page.url}")
                except Exception as e:
                    logger.warning(f"   页面 #{page_count[0]} 等待超时: {e}")

            asyncio.create_task(wait_load())

        self._context.on("page", on_page)

        # 获取或创建第一个页面
        if self._context.pages:
            self._page = self._context.pages[0]
            logger.info(f"使用现有页面: {self._page.url}")
        else:
            self._page = await self._context.new_page()
            logger.info(f"创建新页面: {self._page.url}")

        # 导航到起始 URL
        logger.info(f"正在导航到: {start_url}")
        await self._page.goto(start_url, wait_until="domcontentloaded")

        logger.info("✅ 浏览器已启动，可以开始录制")
        self._is_recording = True

        # TODO: 启动 WebSocket 服务器（后续添加）
        # await self._start_websocket_server()

    async def stop_recording(self) -> Dict[str, Any]:
        """
        停止录制并返回会话信息（异步版本）

        Returns:
            包含录制信息的字典
        """
        logger.info("正在停止录制...")
        self._is_recording = False

        # 获取统计信息
        page_count = len(self._context.pages)
        logger.info(f"总页面数: {page_count}")

        for i, page in enumerate(self._context.pages, 1):
            try:
                url = page.url
                title = await page.title()
                logger.info(f"  页面 {i}: {url} - {title}")
            except Exception as e:
                logger.warning(f"  页面 {i}: 无法访问 ({e})")

        # 关闭浏览器
        await self._close_browser()

        return {"status": "stopped", "total_pages": page_count, "message": "录制已停止"}

    async def _close_browser(self):
        """关闭浏览器（异步版本）"""
        logger.info("正在关闭浏览器...")

        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            # ⭐ 正确退出 Playwright 上下文管理器
            if self._playwright_context:
                await self._playwright_context.__aexit__(None, None, None)

            logger.info("✅ 浏览器已关闭")
        except Exception as e:
            logger.error(f"关闭浏览器时出错: {e}")

    @property
    def is_recording(self) -> bool:
        """是否正在录制"""
        return self._is_recording


# ========== 测试代码 ==========


async def test_async_recorder():
    """测试异步录制器"""
    print("=" * 80)
    print("异步浏览器录制器测试（持久化模式 + 扩展）")
    print("=" * 80)

    recorder = AsyncBrowserRecorder()

    try:
        # 启动录制
        await recorder.start_recording("https://www.baidu.com")

        print("\n" + "=" * 80)
        print("✅ 浏览器已启动，请手动测试：")
        print("=" * 80)
        print("\n核心测试（验证异步 API + 持久化模式）：")
        print("  1. 在百度搜索")
        print("  2. 点击第一个搜索结果（观察终端是否有 [新页面] 日志）")
        print("  3. 回到搜索结果页")
        print("  4. 点击第二个搜索结果（关键测试！）")
        print("  5. 手动新建标签页（Ctrl+T）输入网址")
        print("\n预期结果：")
        print("  ✅ 终端显示 [新页面 #2], [新页面 #3] 等日志")
        print("  ✅ 所有新标签页都能正常显示内容（不是空白页）")
        print("  ✅ 扩展已加载（能捕获用户操作）")
        print("=" * 80)

        # 等待用户输入
        await asyncio.get_event_loop().run_in_executor(
            None, input, "\n⏸️  完成测试后按 Enter 键停止录制..."
        )

        # 停止录制
        result = await recorder.stop_recording()

        print("\n" + "=" * 80)
        print("测试完成")
        print(f"状态: {result['status']}")
        print(f"总页面数: {result['total_pages']}")
        print("=" * 80)

        if result["total_pages"] > 1:
            print("\n✅ 成功！异步 API + 持久化模式能正常处理新标签页！")
            print("   可以开始完整重构 browser_recorder.py 了")
        else:
            print("\n⚠️  警告：只检测到 1 个页面，可能还有问题")

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        await recorder._close_browser()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        await recorder._close_browser()


if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_async_recorder())
