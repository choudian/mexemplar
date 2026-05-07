from src.business.utils.high_risk_api_detector import detect_high_risk_apis


def test_desktop_trial_high_risk_api_uses_shared_detector():
    assert detect_high_risk_apis("import subprocess\nsubprocess.run(['echo', 'x'])") == [
        "subprocess"
    ]
    assert detect_high_risk_apis("import pyautogui\npyautogui.click(1, 2)") == []
