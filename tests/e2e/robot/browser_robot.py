import asyncio
import threading
from typing import Optional


class BrowserRobot:
    def __init__(self) -> None:
        self._context = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

    async def attach(self, context, loop: asyncio.AbstractEventLoop) -> None:
        self._context = context
        self._loop = loop
        self._ready.set()

    def wait_ready(self, timeout: float = 30.0) -> None:
        if not self._ready.wait(timeout):
            raise TimeoutError("BrowserRobot: 浏览器未在超时内就绪")

    def navigate(self, url: str, timeout: float = 30.0) -> None:
        async def _do():
            page = await self._resolve_page()
            await page.goto(url)

        self._run(_do(), timeout)

    def click(self, selector: str, timeout: float = 10.0) -> None:
        async def _do():
            page = await self._resolve_page()
            await page.click(selector)

        self._run(_do(), timeout)

    def fill(self, selector: str, text: str, timeout: float = 10.0) -> None:
        async def _do():
            page = await self._resolve_page()
            await page.fill(selector, text)

        self._run(_do(), timeout)

    def wait_for_selector(self, selector: str, timeout_ms: int = 10_000) -> None:
        async def _do():
            page = await self._resolve_page()
            await page.wait_for_selector(selector, timeout=timeout_ms)

        self._run(_do(), timeout_ms / 1000 + 1)

    def text_content(self, selector: str, timeout: float = 10.0) -> str:
        async def _do():
            page = await self._resolve_page()
            return await page.text_content(selector) or ""

        return self._run(_do(), timeout)

    def current_url(self, timeout: float = 10.0) -> str:
        async def _do():
            page = await self._resolve_page()
            return page.url

        return self._run(_do(), timeout)

    async def _resolve_page(self):
        if self._context is None:
            raise RuntimeError("BrowserRobot 尚未绑定 BrowserContext")
        for page in self._context.pages:
            if not page.url.startswith("chrome-extension://"):
                return page
        return await self._context.new_page()

    def _run(self, coro, timeout: float):
        if self._loop is None:
            raise RuntimeError("BrowserRobot 尚未绑定 event loop")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)
