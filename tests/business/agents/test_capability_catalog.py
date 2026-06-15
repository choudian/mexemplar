from src.business.agents.tools.capability_catalog import (
    CapabilityCatalogItem,
    CapabilityDiscoveryPolicy,
    render_capability_catalog,
    search_capability_catalog,
)


def _policy(**overrides) -> CapabilityDiscoveryPolicy:
    values = {
        "full_catalog_max_items": 20,
        "full_catalog_max_chars": 6000,
        "search_default_limit": 10,
        "search_max_limit": 25,
        "result_description_max_chars": 500,
    }
    values.update(overrides)
    return CapabilityDiscoveryPolicy(**values)


def _tool(name: str, description: str = "") -> CapabilityCatalogItem:
    return CapabilityCatalogItem(kind="tool", name=name, description=description)


def _composition(
    name: str,
    description: str = "",
    applicability: str = "",
) -> CapabilityCatalogItem:
    return CapabilityCatalogItem(
        kind="composition",
        name=name,
        description=description,
        applicability=applicability,
    )


def test_catalog_boundary_uses_full_mode_and_overflow_hides_names():
    items = [_tool(f"能力{i:02d}", "简短说明") for i in range(20)]
    at_boundary = render_capability_catalog(items, _policy(), include_descriptions=True)

    assert at_boundary.mode == "full"
    assert "能力00" in at_boundary.content
    assert at_boundary.item_count == 20

    overflow = render_capability_catalog(
        items + [_tool("绝不能泄漏的能力", "绝不能泄漏的描述")],
        _policy(),
        include_descriptions=True,
    )

    assert overflow.mode == "deferred"
    assert overflow.item_count == 21
    assert "绝不能泄漏的能力" not in overflow.content
    assert "绝不能泄漏的描述" not in overflow.content
    assert "search_tools" in overflow.content
    assert len(overflow.content) < 1000


def test_one_hundred_item_catalog_stays_bounded_and_hides_every_name():
    items = [_tool(f"绝不能泄漏能力{i:03d}", f"绝不能泄漏描述{i:03d}") for i in range(100)]

    rendered = render_capability_catalog(items, _policy(), include_descriptions=True)

    assert rendered.mode == "deferred"
    assert rendered.item_count == 100
    assert len(rendered.content) < 1000
    assert all(item.name not in rendered.content for item in items)
    assert all(item.description not in rendered.content for item in items)


def test_catalog_character_threshold_uses_actual_rendering_level():
    item = _tool("短名称", "x" * 200)
    verbose = render_capability_catalog(
        [item],
        _policy(full_catalog_max_chars=180),
        include_descriptions=True,
    )
    lightweight = render_capability_catalog(
        [item],
        _policy(full_catalog_max_chars=180),
        include_descriptions=False,
    )

    assert verbose.mode == "deferred"
    assert lightweight.mode == "full"
    assert "x" * 20 not in lightweight.content


def test_empty_catalog_has_explicit_no_capabilities_message():
    rendered = render_capability_catalog([], _policy())

    assert rendered.mode == "empty"
    assert rendered.item_count == 0
    assert "当前没有用户自定义" in rendered.content


def test_search_ranking_kind_filter_and_selectors_are_deterministic():
    items = [
        _tool("报告", "精确名称"),
        _tool("报告生成", "前缀名称"),
        _tool("周报报告助手", "名称包含"),
        _tool("材料整理", "用于生成报告"),
        _composition("报告", applicability="组合精确名称"),
        _composition("资料组合", applicability="报告场景"),
        _tool("无关能力", "没有匹配"),
    ]

    page = search_capability_catalog(items, _policy(), query="报告")
    assert [item.name for item in page.items] == [
        "报告",
        "报告",
        "报告生成",
        "周报报告助手",
        "材料整理",
        "资料组合",
    ]
    assert [item.kind for item in page.items[:2]] == ["tool", "composition"]
    assert page.items[0].selector == "技能:报告"
    assert page.items[1].selector == "技能组合:报告"

    compositions = search_capability_catalog(
        items,
        _policy(),
        query="报告",
        kind="composition",
    )
    assert [item.kind for item in compositions.items] == ["composition", "composition"]


def test_search_text_includes_name_description_and_applicability():
    item = _composition(
        "资料整理",
        description="归档材料",
        applicability="适合季度报告",
    )

    assert item.search_text == "资料整理 归档材料 适合季度报告".casefold()


def test_search_browse_paginates_one_hundred_items_without_gaps():
    items = [_tool(f"能力{i:03d}", f"描述{i}") for i in range(100)]
    seen = []
    offset = 0

    while True:
        page = search_capability_catalog(
            items,
            _policy(),
            query="",
            offset=offset,
            limit=25,
        )
        seen.extend(item.name for item in page.items)
        if page.next_offset is None:
            break
        offset = page.next_offset

    assert seen == [f"能力{i:03d}" for i in range(100)]
    assert len(set(seen)) == 100

    past_end = search_capability_catalog(items, _policy(), offset=1000, limit=25)
    assert past_end.total == 100
    assert past_end.items == ()
    assert past_end.next_offset is None


def test_search_clamps_page_size_and_description_length():
    items = [_tool(f"能力{i:02d}", "长" * 100) for i in range(30)]
    page = search_capability_catalog(
        items,
        _policy(search_max_limit=7, result_description_max_chars=20),
        limit=99,
    )
    payload = page.to_dict()

    assert page.limit == 7
    assert len(page.items) == 7
    assert page.next_offset == 7
    assert payload["items"][0]["description"] == "长" * 20


def test_search_rejects_invalid_kind_offset_and_limit():
    items = [_tool("能力")]

    for kwargs, message in (
        ({"kind": "unknown"}, "kind"),
        ({"offset": -1}, "offset"),
        ({"offset": "bad"}, "offset"),
        ({"limit": 0}, "limit"),
        ({"limit": "bad"}, "limit"),
    ):
        try:
            search_capability_catalog(items, _policy(), **kwargs)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"Expected invalid search arguments to fail: {kwargs}")
