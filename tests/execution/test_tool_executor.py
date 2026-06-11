import sys
from pathlib import Path

from src.execution import tool_executor


def test_tool_code_relative_file_outputs_are_scoped_to_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(data_dir))
    monkeypatch.setattr(tool_executor, "_get_venv_python", lambda: sys.executable)

    code = """
import os
from pathlib import Path

async def execute(**kwargs):
    Path("report.txt").write_text("hello", encoding="utf-8")
    output_dir = os.environ["MEXEMPLAR_OUTPUT_DIR"]
    return {
        "success": True,
        "message": os.getcwd(),
        "data": {
            "data_dir": os.environ["MEXEMPLAR_DATA_DIR"],
            "tool_run_dir": os.environ["MEXEMPLAR_TOOL_RUN_DIR"],
            "output_dir": output_dir,
        },
    }
"""

    result = tool_executor.run_tool_code(code, parameters={})

    assert result["success"] is True
    output_dir = Path(result["output_dir"])
    assert output_dir.parent == data_dir / "tool_runs"
    assert Path(result["message"]) == output_dir
    assert result["data"] == {
        "data_dir": str(data_dir),
        "tool_run_dir": str(output_dir),
        "output_dir": str(output_dir),
    }
    assert result["output_files"] == ["report.txt"]
    assert (output_dir / "report.txt").read_text(encoding="utf-8") == "hello"
