import ast
import json
from pathlib import Path

from src.data.config_contract import (
    ConfigScope,
    DEFAULT_CONFIG_CONTRACT,
    flatten_mapping,
    schema_leaf_paths,
    validate_template_file,
)
from src.data.config_models import AppConfig


def test_config_example_is_schema_compatible_and_secret_safe():
    repo_root = Path(__file__).resolve().parents[2]

    assert validate_template_file(repo_root / "config.example.json") == ()


def test_serialized_app_config_omits_deprecated_user_configuration_keys():
    data = AppConfig().to_dict()

    assert "debug" not in data
    assert "compression_model_provider" not in data["ai"]
    assert "record_mouse_move" not in data["recording"]
    assert "enabled" not in data["recording"]["websocket"]


def test_serialized_app_config_redacts_execution_review_model_secret():
    config = AppConfig()
    config.self_improvement.execution_review.model.api_key = "not-a-real-secret"

    assert config.to_dict()["self_improvement"]["execution_review"]["model"]["api_key"] is None


def test_config_example_lists_every_file_backed_schema_key():
    repo_root = Path(__file__).resolve().parents[2]
    template = json.loads((repo_root / "config.example.json").read_text(encoding="utf-8"))
    template_paths = set(flatten_mapping(template))
    expected_paths = {
        path
        for path in schema_leaf_paths()
        if DEFAULT_CONFIG_CONTRACT.classify(path).scope is ConfigScope.FILE_DB
    }

    assert template_paths == expected_paths


def test_every_literal_unified_config_consumer_key_has_a_contract_classification():
    repo_root = Path(__file__).resolve().parents[2]
    tree = ast.parse((repo_root / "src" / "data" / "unified_config.py").read_text(encoding="utf-8"))
    methods = {
        "get",
        "_get_bounded_positive_int",
        "_get_secret",
        "_set_secret",
        "_clear_secret",
        "_get_canonical_with_legacy",
    }
    literal_keys = set()

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr in methods
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        literal_keys.add(node.args[0].value)
        if (
            node.func.attr == "_get_canonical_with_legacy"
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            literal_keys.add(node.args[1].value)

    unknown = {
        key
        for key in literal_keys
        if DEFAULT_CONFIG_CONTRACT.classify(key).scope is ConfigScope.UNKNOWN
    }
    assert unknown == set()
