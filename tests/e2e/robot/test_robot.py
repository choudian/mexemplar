from __future__ import annotations

from .browser_robot import BrowserRobot
from .ui_robot import UIRobot
from .wait_helper import WaitHelper

__test__ = False


class TestRobot:
    def __init__(self, window, *, timeout_profile: str = "mock") -> None:
        self.ui = UIRobot(window)
        self.browser = BrowserRobot()
        self.wait = WaitHelper(timeout_profile=timeout_profile)
