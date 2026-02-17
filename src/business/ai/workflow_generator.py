"""
工作流生成器

整合数据预处理、视觉分析和语义分析，从录制数据生成完整的工作流定义
"""

import json
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

from src.recording.recorder import Action, RecordingSession
from src.business.ai.preprocessing import DataPreprocessor, PreprocessingResult
from src.business.ai.vision_analyzer import VisionAnalyzer
from src.business.ai.semantic_analyzer import SemanticAnalyzer
from src.data.models import Tool

logger = logging.getLogger(__name__)


class WorkflowGenerator:
    """工作流生成器 - 从录制数据生成可执行的工作流"""

    def __init__(self, api_key: Optional[str] = None, enable_vision: bool = True):
        """
        初始化工作流生成器

        Args:
            api_key: Anthropic API 密钥
            enable_vision: 是否启用视觉分析（需要额外的 API 调用）
        """
        self.preprocessor = DataPreprocessor()
        self.semantic_analyzer = SemanticAnalyzer(api_key=api_key)
        self.vision_analyzer = VisionAnalyzer(api_key=api_key) if enable_vision else None
        self.enable_vision = enable_vision

    def generate(
        self, recording_session: RecordingSession, options: Optional[Dict[str, Any]] = None
    ) -> Tool:
        """
        从录制会话生成工具定义

        Args:
            recording_session: 录制会话数据
            options: 生成选项
                - include_vision_analysis: 是否包含视觉分析（默认为 enable_vision）
                - analyze_screenshots: 是否分析截图（默认为 True）
                - max_screenshots: 最多分析多少张截图（默认为 5）

        Returns:
            Tool: 生成的工具定义
        """
        logger.info(f"开始生成工作流: {recording_session.recording_id}")

        options = options or {}

        # 步骤1: 数据预处理
        logger.info("步骤1: 数据预处理")
        preprocessing_result = self.preprocessor.preprocess(recording_session.actions)

        # 步骤2: 意图分析
        logger.info("步骤2: 意图分析")
        intent = self.semantic_analyzer.analyze_intent(
            actions=recording_session.actions, metadata=preprocessing_result.metadata
        )

        # 步骤3: 视觉分析（可选）
        vision_analysis = None
        if self.enable_vision and options.get("include_vision_analysis", True):
            if options.get("analyze_screenshots", True) and preprocessing_result.screenshots:
                logger.info("步骤3: 视觉分析")
                max_screenshots = options.get("max_screenshots", 5)
                screenshots_to_analyze = preprocessing_result.screenshots[:max_screenshots]

                try:
                    vision_analysis = self.vision_analyzer.analyze_screenshots_sequence(
                        image_paths=screenshots_to_analyze,
                        context=f"任务: {intent.get('task_name', '未知任务')}",
                    )
                except Exception as e:
                    logger.warning(f"视觉分析失败: {e}，继续使用其他信息生成工作流")

        # 步骤4: 参数提取
        logger.info("步骤4: 参数提取")
        parameters = self.semantic_analyzer.extract_parameters(
            actions=recording_session.actions, intent=intent
        )

        # 步骤5: 工作流生成
        logger.info("步骤5: 工作流生成")
        workflow = self.semantic_analyzer.generate_workflow(
            actions=recording_session.actions,
            intent=intent,
            parameters=parameters,
            vision_analysis=vision_analysis,
        )

        # 步骤6: 创建 Tool 对象
        tool = self._create_tool(workflow, recording_session)

        logger.info(f"工作流生成完成: {tool.tool_name}")
        return tool

    def generate_from_actions(
        self, actions: List[Action], options: Optional[Dict[str, Any]] = None
    ) -> Tool:
        """
        从操作列表直接生成工具定义

        Args:
            actions: 操作列表
            options: 生成选项

        Returns:
            Tool: 生成的工具定义
        """
        # 创建临时 RecordingSession
        from datetime import datetime
        import uuid

        temp_session = RecordingSession(
            recording_id=str(uuid.uuid4()),
            status="stopped",
            recording_mode=actions[0].recording_mode if actions else "desktop",
            start_time=datetime.now().timestamp(),
            end_time=datetime.now().timestamp(),
            actions=actions,
            metadata={},
        )

        return self.generate(temp_session, options)

    def _create_tool(self, workflow: Dict[str, Any], session: RecordingSession) -> Tool:
        """从工作流定义创建 Tool 对象"""
        if not workflow:
            # 如果工作流生成失败，创建基础工具
            logger.warning("工作流生成失败，创建基础工具定义")
            return self._create_basic_tool(session)

        from datetime import datetime

        tool = Tool(
            tool_name=workflow.get("tool_name", "未知工具"),
            description=workflow.get("description", ""),
            parameters=workflow.get("parameters", []),
            steps=workflow.get("steps", []),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        return tool

    def _create_basic_tool(self, session: RecordingSession) -> Tool:
        """创建基础工具定义（当 AI 生成失败时）"""
        from datetime import datetime

        # 简单地转换操作为步骤
        steps = []
        for idx, action in enumerate(session.actions, 1):
            step = {
                "step_number": idx,
                "step_name": f"步骤{idx}: {action.action_type}",
                "action_type": action.action_type,
                "description": f"执行 {action.action_type} 操作",
                "parameters": action.parameters,
                "locator_info": (
                    {
                        "type": "coordinate",
                        "value": f"{action.parameters.get('x', 0)},{action.parameters.get('y', 0)}",
                    }
                    if action.recording_mode == "desktop"
                    else None
                ),
            }
            steps.append(step)

        tool = Tool(
            tool_name=f"录制的工具 ({len(session.actions)} 个操作)",
            description=f"从录制会话 {session.recording_id} 生成",
            parameters=[],
            steps=steps,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        return tool

    def validate_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证工作流定义的完整性

        Args:
            workflow: 工作流定义

        Returns:
            Dict[str, Any]: 验证结果
            {
                'valid': bool,
                'errors': List[str],
                'warnings': List[str],
            }
        """
        errors = []
        warnings = []

        # 检查必需字段
        required_fields = ["tool_name", "description", "steps"]
        for field in required_fields:
            if field not in workflow:
                errors.append(f"缺少必需字段: {field}")

        # 检查步骤
        if "steps" in workflow:
            if not workflow["steps"]:
                errors.append("工作流没有定义任何步骤")

            for idx, step in enumerate(workflow["steps"]):
                step_num = idx + 1

                if "action_type" not in step:
                    errors.append(f"步骤 {step_num} 缺少 action_type")

                if "parameters" not in step:
                    warnings.append(f"步骤 {step_num} 没有定义参数")

                if "locator_info" not in step and step.get("action_type", "").startswith("browser"):
                    warnings.append(f"步骤 {step_num} 没有定义定位信息")

        # 检查参数
        if "parameters" in workflow:
            param_names = set()
            for param in workflow["parameters"]:
                if "name" not in param:
                    errors.append(f"参数缺少 name 字段")

                if param["name"] in param_names:
                    errors.append(f"参数名重复: {param['name']}")
                else:
                    param_names.add(param["name"])

            # 检查步骤中的参数引用
            if "steps" in workflow:
                for step in workflow["steps"]:
                    for key, value in step.get("parameters", {}).items():
                        if (
                            isinstance(value, str)
                            and value.startswith("{{")
                            and value.endswith("}}")
                        ):
                            param_name = value[2:-2].strip()
                            if param_name not in param_names:
                                warnings.append(f"步骤引用了未定义的参数: {param_name}")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def export_workflow(self, workflow: Dict[str, Any], output_path: str) -> bool:
        """
        导出工作流定义到 JSON 文件

        Args:
            workflow: 工作流定义
            output_path: 输出文件路径

        Returns:
            bool: 是否成功
        """
        try:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(workflow, f, ensure_ascii=False, indent=2)

            logger.info(f"工作流已导出到: {output_path}")
            return True

        except Exception as e:
            logger.error(f"导出工作流失败: {e}")
            return False

    def import_workflow(self, input_path: str) -> Optional[Dict[str, Any]]:
        """
        从 JSON 文件导入工作流定义

        Args:
            input_path: 输入文件路径

        Returns:
            Optional[Dict[str, Any]]: 工作流定义，失败返回 None
        """
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                workflow = json.load(f)

            logger.info(f"工作流已从 {input_path} 导入")
            return workflow

        except Exception as e:
            logger.error(f"导入工作流失败: {e}")
            return None

    def close(self):
        """关闭所有分析器"""
        if self.semantic_analyzer:
            self.semantic_analyzer.close()
        if self.vision_analyzer:
            self.vision_analyzer.close()
