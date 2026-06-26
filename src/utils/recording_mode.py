"""RecordingMode 常量类(分层修复:从 recording 层下沉到 utils)。

纯常量 + display_defaults 查表,无外部依赖。recording / business / data 层共享,
下沉到 utils 后各层都从本模块上调 import,避免 data 层反向依赖 recording 层。
"""


class RecordingMode:
    BROWSER = "browser"
    DESKTOP = "desktop"
    EXTENSION_TRIGGERED = "extension_triggered"

    @classmethod
    def display_defaults(cls, mode: str) -> dict:
        if mode == cls.EXTENSION_TRIGGERED:
            return {"browser_type": "chrome", "app_name": "Chrome", "process_name": "chrome"}
        return {"browser_type": "chromium", "app_name": "Browser", "process_name": "browser"}
