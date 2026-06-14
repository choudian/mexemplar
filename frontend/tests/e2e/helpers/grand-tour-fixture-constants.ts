/**
 * Real Grand Tour 夹具技能常量（与后端 src/data/grand_tour_fixture_seed.py 保持一致）。
 *
 * grand-tour sidecar 启动时（MEXEMPLAR_REAL_GRAND_TOUR=1）由
 * ensure_fixture_skill() 注入到 ToolRepository，作为技能组合"至少 2 成员"
 * 契约的第二成员占位。生产环境绝不注入。
 *
 * 修改这里的值必须同步修改后端 seed 常量。
 */
export const GRAND_TOUR_FIXTURE_SKILL_NAME = "Grand Tour Fixture Echo";
export const GRAND_TOUR_FIXTURE_SKILL_ID = "fixture.grand_tour.echo";
