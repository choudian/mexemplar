"""
大脑架构业务逻辑子包

公开服务：
- DistillationService: Segment 沉淀
- BrainContextBuilder: 上下文构建
- BrainBackgroundWorker: 后台工作线程
- DecayRouter: 热区衰减路由
- ArchiveService: 归档分层聚合
- RetrievalService: 归档区检索
- SegmentService: Segment 边界管理
- PredictionService: 猜测生成与验证
- BrainManagementService: 大脑管理 API facade
- SpecialistService: 专员管理、招募和技能池约束
- SkillService: 方法论资产生命周期与 supersede
- SkillEquipmentService: 方法论装备状态机与默认装备传播
- SkillBootstrapService: 内置方法论 seed / fallback bootstrap
- SkillReferenceCounterService: 方法论引用计数
"""
