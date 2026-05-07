import ast

from src.business.agents.tools import recording_data_tools
from src.business.agents.tools.recording_data_tools import create_recording_tools


def test_browser_recording_tool_names_stay_canonical():
    names = [tool.name for tool in create_recording_tools("missing-browser-rec")]

    assert names == [
        "describe_data",
        "query_data",
        "execute_code",
        "read_recording",
        "read_field_chunk",
        "analyze_image",
    ]


def test_recording_data_tools_does_not_import_sqlglot_directly():
    tree = ast.parse(open(recording_data_tools.__file__, encoding="utf-8").read())

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    assert not any(name == "sqlglot" or name.startswith("sqlglot.") for name in imports)
