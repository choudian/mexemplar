from unittest.mock import patch

from src.recording.system_proxy import SystemProxyManager


def _prepare_mock_registry(mock_reg):
    mock_reg.KEY_QUERY_VALUE = 1
    mock_reg.KEY_SET_VALUE = 2
    mock_reg.HKEY_CURRENT_USER = object()
    mock_reg.REG_DWORD = 4
    mock_reg.REG_SZ = 1
    return mock_reg.OpenKey.return_value.__enter__.return_value


def test_enable_sets_registry():
    with patch("src.recording.system_proxy.winreg") as mock_reg:
        _prepare_mock_registry(mock_reg)
        mock_reg.QueryValueEx.side_effect = [
            (1, mock_reg.REG_DWORD),
            ("original:1234", mock_reg.REG_SZ),
        ]

        manager = SystemProxyManager()
        manager.enable("127.0.0.1", 8080)

        calls = mock_reg.SetValueEx.call_args_list
        assert any(call.args[1] == "ProxyEnable" and call.args[4] == 1 for call in calls)
        assert any(call.args[1] == "ProxyServer" and call.args[4] == "127.0.0.1:8080" for call in calls)


def test_disable_restores_registry():
    with patch("src.recording.system_proxy.winreg") as mock_reg:
        _prepare_mock_registry(mock_reg)
        manager = SystemProxyManager()
        manager._original_proxy = "original:1234"
        manager._was_enabled = True
        manager._snapshot_taken = True

        manager.disable()

        calls = mock_reg.SetValueEx.call_args_list
        assert any(call.args[1] == "ProxyEnable" and call.args[4] == 1 for call in calls)
        assert any(call.args[1] == "ProxyServer" and call.args[4] == "original:1234" for call in calls)


def test_disable_clears_proxy_server_when_original_missing():
    with patch("src.recording.system_proxy.winreg") as mock_reg:
        _prepare_mock_registry(mock_reg)
        manager = SystemProxyManager()
        manager._original_proxy = None
        manager._was_enabled = False
        manager._snapshot_taken = True

        manager.disable()

        calls = mock_reg.SetValueEx.call_args_list
        assert any(call.args[1] == "ProxyEnable" and call.args[4] == 0 for call in calls)
        assert any(call.args[1] == "ProxyServer" and call.args[4] == "" for call in calls)


def test_disable_without_prior_enable_is_noop():
    with patch("src.recording.system_proxy.winreg") as mock_reg:
        manager = SystemProxyManager()
        manager.disable()
        mock_reg.OpenKey.assert_not_called()
