from __future__ import annotations

import logging

from src.utils.logger import setup_logger


def test_setup_logger_uses_runtime_data_dir(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(data_dir))

    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    previous_level = root_logger.level

    for handler in previous_handlers:
        root_logger.removeHandler(handler)

    try:
        logger = setup_logger(
            name="mexemplar.test.runtime_data_dir",
            console_output=False,
            file_output=True,
            log_level=logging.INFO,
        )
        logger.info("runtime data dir log marker")
        for handler in root_logger.handlers:
            handler.flush()

        log_file = data_dir / "logs" / "mexemplar.log"
        assert log_file.exists()
        assert "runtime data dir log marker" in log_file.read_text(encoding="utf-8")
    finally:
        for handler in list(root_logger.handlers):
            handler.close()
            root_logger.removeHandler(handler)
        for handler in previous_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(previous_level)
