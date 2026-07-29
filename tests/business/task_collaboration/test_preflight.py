import pytest

from src.business.task_collaboration.preflight import (
    TaskNodePathContext,
    find_outside_workspace_path_risks,
)


def test_windows_absolute_path_outside_executor_workspace_is_reported():
    nodes = [
        TaskNodePathContext(
            node_id="layout",
            description=(
                r"修改 E:\code\Exemplar\frontend\src\layoutDag.ts，"
                r"并读取 `E:\code\Exemplar\frontend\package.json`。"
            ),
            workspace_root=r"E:\code\test\Mexemplar",
        )
    ]

    risks = find_outside_workspace_path_risks(nodes)

    assert [(risk.code, risk.severity, risk.node_id, risk.absolute_path) for risk in risks] == [
        (
            "absolute_path_outside_workspace",
            "high",
            "layout",
            r"E:\code\Exemplar\frontend\src\layoutDag.ts",
        ),
        (
            "absolute_path_outside_workspace",
            "high",
            "layout",
            r"E:\code\Exemplar\frontend\package.json",
        ),
    ]
    assert risks[0].workspace_root == r"E:\code\test\Mexemplar"
    assert "不在执行体工作区内" in risks[0].message


def test_paths_within_workspace_are_not_reported_and_boundary_sibling_is():
    nodes = [
        TaskNodePathContext(
            node_id="mixed",
            description=(
                r"保留 E:\code\Exemplar\src\a.py；" r"不要误写 E:\code\Exemplar-old\src\a.py。"
            ),
            workspace_root=r"e:\CODE\Exemplar",
        )
    ]

    risks = find_outside_workspace_path_risks(nodes)

    assert [risk.absolute_path for risk in risks] == [r"E:\code\Exemplar-old\src\a.py"]


def test_parent_segments_cannot_lexically_escape_workspace():
    nodes = [
        TaskNodePathContext(
            node_id="escape",
            description=r"写 E:\workspace\app\src\..\..\outside.py",
            workspace_root=r"E:\workspace\app",
        )
    ]

    risks = find_outside_workspace_path_risks(nodes)

    assert [risk.absolute_path for risk in risks] == [r"E:\workspace\app\src\..\..\outside.py"]


def test_posix_paths_are_checked_without_touching_the_filesystem():
    nodes = [
        TaskNodePathContext(
            node_id="posix",
            description="读取 /workspace/app/pyproject.toml，再写 `/other/app/out.txt`。",
            workspace_root="/workspace/app",
        )
    ]

    risks = find_outside_workspace_path_risks(nodes)

    assert [risk.absolute_path for risk in risks] == ["/other/app/out.txt"]


def test_relative_paths_urls_and_duplicate_absolute_paths_are_ignored():
    nodes = [
        TaskNodePathContext(
            node_id="dedupe",
            description=(
                "查看 src/main.py 和 https://example.test/a/b；"
                r"再读 `E:\repo\outside.txt` 与 E:\repo\outside.txt。"
            ),
            workspace_root=r"E:\workspace",
        )
    ]

    risks = find_outside_workspace_path_risks(nodes)

    assert [risk.absolute_path for risk in risks] == [r"E:\repo\outside.txt"]


def test_sentence_punctuation_is_not_treated_as_part_of_a_path():
    nodes = [
        TaskNodePathContext(
            node_id="punctuation",
            description=(
                r"检查 E:\repo\outside.py, 然后检查 /other/repo/file.py. "
                r"最后读取 \\server\share\outside.txt!"
            ),
            workspace_root=r"E:\workspace",
        )
    ]

    risks = find_outside_workspace_path_risks(nodes)

    assert [risk.absolute_path for risk in risks] == [
        r"E:\repo\outside.py",
        "/other/repo/file.py",
        r"\\server\share\outside.txt",
    ]


def test_quoted_paths_with_spaces_are_compared_as_complete_paths():
    nodes = [
        TaskNodePathContext(
            node_id="spaces",
            description=(
                r"保留 `E:\My Project\src\inside.py`，" '并检查 "E:\\Other Project\\outside.py"。'
            ),
            workspace_root=r"E:\My Project",
        )
    ]

    risks = find_outside_workspace_path_risks(nodes)

    assert [risk.absolute_path for risk in risks] == [r"E:\Other Project\outside.py"]


def test_unquoted_windows_path_with_spaces_inside_workspace_is_not_reported():
    risks = find_outside_workspace_path_risks(
        [
            TaskNodePathContext(
                node_id="inside-spaces",
                description=r"改 C:\Program Files\ws\sub\a.txt",
                workspace_root=r"C:\Program Files\ws",
            )
        ]
    )

    assert risks == []


def test_unquoted_windows_path_with_spaces_outside_workspace_is_reported_in_full():
    risks = find_outside_workspace_path_risks(
        [
            TaskNodePathContext(
                node_id="outside-spaces",
                description=r"请修改 C:\Program Files\Foo\a.txt",
                workspace_root=r"C:\Program Files\ws",
            )
        ]
    )

    assert [risk.absolute_path for risk in risks] == [r"C:\Program Files\Foo\a.txt"]


@pytest.mark.parametrize(
    "description",
    [
        r"改 E:\code\ws 下的文件",
        r"在 E:\code\ws 中新增模块",
        r"把结果写到 E:\code\ws 里",
        r"请在 E:\code\ws 目录下实现功能",
    ],
)
def test_workspace_root_followed_by_prose_is_not_reported(description):
    """未加引号时，路径与紧随其后的中文无法分辨，不得据此误报区内节点。

    误报会让人学会忽略整份清单，代价比漏报大。
    """
    risks = find_outside_workspace_path_risks(
        [
            TaskNodePathContext(
                node_id="prose",
                description=description,
                workspace_root=r"E:\code\ws",
            )
        ]
    )

    assert risks == []


def test_prose_after_a_diverging_path_still_reports():
    """吞进散文不能掩盖真正的分叉：目录段不同就必须报。"""
    risks = find_outside_workspace_path_risks(
        [
            TaskNodePathContext(
                node_id="diverging",
                description=r"在项目 E:\code\Exemplar 下，阅读设计文档并实现 layoutDag",
                workspace_root=r"E:\code\test\Mexemplar",
            )
        ]
    )

    assert [risk.node_id for risk in risks] == ["diverging"]


def test_ancestor_of_workspace_root_is_not_reported():
    """提到工作区的上级目录不算越界，只是没写到底。"""
    risks = find_outside_workspace_path_risks(
        [
            TaskNodePathContext(
                node_id="ancestor",
                description=r"仓库都放在 E:\code 下",
                workspace_root=r"E:\code\ws",
            )
        ]
    )

    assert risks == []


def test_workspace_root_must_be_absolute():
    with pytest.raises(ValueError, match="workspace_root must be absolute"):
        find_outside_workspace_path_risks(
            [
                TaskNodePathContext(
                    node_id="bad-root",
                    description=r"写 E:\repo\file.py",
                    workspace_root="relative/root",
                )
            ]
        )
