import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.recording.cert_manager import CertManager, DEFAULT_CERT_PATH, MITMPROXY_CERT_SUBJECT


def _make_temp_file(name: str) -> Path:
    base = Path.cwd() / ".reports" / "pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{uuid.uuid4().hex}_{name}"


def test_is_installed_returns_false_when_cert_missing():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        manager = CertManager()
        assert manager.is_installed() is False


def test_is_installed_returns_true_when_cert_present():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=f"Subject: {MITMPROXY_CERT_SUBJECT}\nIssuer: mitmproxy",
            stderr="",
        )
        manager = CertManager()
        assert manager.is_installed() is True


def test_default_cert_path_uses_public_cer():
    manager = CertManager()
    assert manager.cert_path == DEFAULT_CERT_PATH
    assert manager.cert_path.name == "mitmproxy-ca-cert.cer"


def test_install_calls_certutil():
    cert_file = _make_temp_file("mitmproxy-ca-cert.cer")
    cert_file.write_bytes(b"fake cert data")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        manager = CertManager(cert_path=cert_file)
        result = manager.install()
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "certutil" in args[0].lower()
        assert "-addstore" in args


def test_install_returns_false_when_cert_file_missing():
    manager = CertManager(cert_path=Path("/nonexistent/mitmproxy-ca-cert.cer"))
    result = manager.install()
    assert result is False


def test_install_returns_false_on_nonzero_exit():
    cert_file = _make_temp_file("mitmproxy-ca-cert.cer")
    cert_file.write_bytes(b"fake cert")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Access denied")
        manager = CertManager(cert_path=cert_file)
        result = manager.install()
        assert result is False


def test_is_installed_returns_false_on_subprocess_error():
    with patch("subprocess.run", side_effect=FileNotFoundError("certutil not found")):
        manager = CertManager()
        assert manager.is_installed() is False


def test_ensure_installed_skips_when_already_installed():
    manager = CertManager()
    with patch.object(manager, "is_installed", return_value=True):
        with patch.object(manager, "install") as mock_install:
            result = manager.ensure_installed()
            assert result is True
            mock_install.assert_not_called()
