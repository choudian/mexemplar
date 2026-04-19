from unittest.mock import patch

import src.main as main_module


def test_main_triggers_startup_recovery(monkeypatch):
    monkeypatch.setattr("sys.argv", ["mexemplar", "--gui"])

    with patch.object(main_module, "_init_logging"):
        with patch.object(main_module, "_register_shutdown_handlers"):
            with patch.object(main_module, "get_unified_config"):
                with patch.object(main_module.RecordingRepository, "ensure_startup_recovery") as mock_recovery:
                    with patch.object(main_module, "_launch_gui", return_value=0):
                        result = main_module.main()

    assert result == 0
    mock_recovery.assert_called_once_with()
