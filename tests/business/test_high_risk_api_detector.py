from src.business.utils.high_risk_api_detector import detect_high_risk_apis


def test_detects_high_risk_api_labels():
    code = """
import subprocess
import webbrowser
import win32api
from pywinauto import Application

subprocess.run(["cmd", "/c", "echo hi"])
webbrowser.open("https://example.com")
os.startfile("C:/tmp/a.txt")
Application().connect(title="x")
url = "wechat:"
"""
    labels = detect_high_risk_apis(code)

    assert "subprocess" in labels
    assert "webbrowser" in labels
    assert "os.startfile" in labels
    assert "pywin32" in labels
    assert "pywinauto" in labels
    assert "win32_protocol_url" in labels


def test_detector_keeps_boundaries_stable():
    assert detect_high_risk_apis('path = "C:\\\\foo\\\\bar.txt"') == []
    assert detect_high_risk_apis("import pyautogui\npyautogui.click(1, 2)") == []
    assert detect_high_risk_apis('url = "mailto:hello@example.com"') == ["win32_protocol_url"]
