import src.main as main_module


def test_legacy_gui_main_fails_closed(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["mexemplar", "--gui"])

    result = main_module.main()

    captured = capsys.readouterr()
    assert result == 2
    assert "Legacy PyQt launch is no longer supported" in captured.err
