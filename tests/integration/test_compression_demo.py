"""
数据压缩功能演示测试脚本

此脚本用于演示数据压缩功能的完整流程，包括：
1. 从 DuckDB 读取录制数据
2. 将数据转换为 Action 对象
3. 执行不同级别的数据压缩
4. 展示压缩前后的详细对比

使用示例:
    # 列出所有可用的录制会话
    python test_compression_demo.py --list

    # 测试指定会话（所有压缩级别）
    python test_compression_demo.py --recording-id rec-20250205-103600 --verbose

    # 测试单个压缩级别
    python test_compression_demo.py --recording-id rec-20250205-103600 --level moderate
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import duckdb
from src.business.ai.preprocessing import (
    CompressionLevel,
    DataPreprocessor,
    PreprocessingResult,
)
from src.recording.recorder import Action, NetworkRequest
from src.utils.logger import setup_logger

# 配置日志
setup_logger()
logger = logging.getLogger(__name__)


class DuckDBReader:
    """从 DuckDB 读取录制数据"""

    def __init__(self, db_path: str):
        """
        初始化 DuckDB 读取器

        Args:
            db_path: DuckDB 数据库文件路径
        """
        self.db_path = db_path
        self.conn = None

    def connect(self) -> bool:
        """
        建立数据库连接

        Returns:
            bool: 连接是否成功
        """
        try:
            if not Path(self.db_path).exists():
                logger.error(f"数据库文件不存在: {self.db_path}")
                return False

            self.conn = duckdb.connect(self.db_path)
            logger.info(f"成功连接到数据库: {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            return False

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")

    def list_recording_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有录制会话

        Returns:
            List[Dict]: 录制会话列表
        """
        if not self.conn:
            logger.error("数据库未连接")
            return []

        try:
            query = """
                SELECT
                    rs.recording_id,
                    rs.status,
                    rs.recording_mode,
                    rs.start_time,
                    rs.end_time,
                    COUNT(a.action_id) as action_count
                FROM recording_sessions rs
                LEFT JOIN actions a ON rs.recording_id = a.recording_id
                GROUP BY rs.recording_id, rs.status, rs.recording_mode, rs.start_time, rs.end_time
                ORDER BY rs.start_time DESC
            """

            result = self.conn.execute(query).fetchall()

            sessions = []
            for row in result:
                sessions.append({
                    'recording_id': row[0],
                    'status': row[1],
                    'recording_mode': row[2],
                    'start_time': row[3],
                    'end_time': row[4],
                    'action_count': row[5] or 0
                })

            logger.info(f"找到 {len(sessions)} 个录制会话")
            return sessions

        except Exception as e:
            logger.error(f"查询录制会话失败: {e}")
            return []

    def get_actions_by_recording_id(self, recording_id: str) -> List[Dict[str, Any]]:
        """
        获取指定录制会话的所有操作

        Args:
            recording_id: 录制会话 ID

        Returns:
            List[Dict]: 操作数据列表
        """
        if not self.conn:
            logger.error("数据库未连接")
            return []

        try:
            # 查询操作和网络请求
            query = """
                SELECT
                    a.action_id,
                    a.action_type,
                    a.recording_mode,
                    a.url,
                    a.parameters,
                    a.dom_element,
                    a.timestamp,
                    a.sequence_number,
                    LIST({
                        'request_id': nr.request_id,
                        'url': nr.url,
                        'method': nr.method,
                        'request_type': nr.request_type,
                        'request_headers': nr.request_headers,
                        'request_body': nr.request_body,
                        'response_status': nr.response_status,
                        'response_headers': nr.response_headers,
                        'response_body': nr.response_body,
                        'duration': nr.duration,
                        'timestamp': nr.timestamp,
                        'is_recommendation': nr.is_recommendation,
                        'importance_level': nr.importance_level
                    }) FILTER (WHERE nr.request_id IS NOT NULL) as network_requests
                FROM actions a
                LEFT JOIN network_requests nr ON a.action_id = nr.action_id
                WHERE a.recording_id = ?
                GROUP BY a.action_id, a.action_type, a.recording_mode, a.url,
                         a.parameters, a.dom_element, a.timestamp, a.sequence_number
                ORDER BY a.sequence_number, a.timestamp
            """

            result = self.conn.execute(query, [recording_id]).fetchall()

            actions = []
            for row in result:
                actions.append({
                    'action_id': row[0],
                    'action_type': row[1],
                    'recording_mode': row[2],
                    'url': row[3],
                    'parameters': row[4],
                    'dom_element': row[5],
                    'timestamp': row[6],
                    'sequence_number': row[7],
                    'network_requests': row[8]  # This is already a list
                })

            logger.info(f"从会话 {recording_id} 中获取到 {len(actions)} 个操作")
            return actions

        except Exception as e:
            logger.error(f"查询操作数据失败: {e}")
            return []


class ActionConverter:
    """将 DuckDB 数据转换为 Action 对象"""

    @staticmethod
    def convert_from_duckdb(duckdb_rows: List[Dict[str, Any]]) -> List[Action]:
        """
        批量转换 DuckDB 数据为 Action 对象

        Args:
            duckdb_rows: DuckDB 查询结果

        Returns:
            List[Action]: Action 对象列表
        """
        actions = []

        for row in duckdb_rows:
            try:
                action = ActionConverter._convert_single_row(row)
                if action:
                    actions.append(action)
            except Exception as e:
                logger.warning(f"转换操作失败 (action_id={row.get('action_id')}): {e}")
                continue

        logger.info(f"成功转换 {len(actions)} 个操作")
        return actions

    @staticmethod
    def _convert_single_row(row: Dict[str, Any]) -> Optional[Action]:
        """
        转换单行数据为 Action 对象

        Args:
            row: DuckDB 查询行数据

        Returns:
            Action: 转换后的 Action 对象
        """
        try:
            # 解析 JSON 字段
            parameters = ActionConverter._parse_json_field(row.get('parameters'))
            dom_element = ActionConverter._parse_json_field(row.get('dom_element'))

            # 解析网络请求
            network_requests = ActionConverter._parse_network_requests(
                row.get('network_requests')
            )

            # 转换时间戳
            timestamp = row['timestamp']
            if isinstance(timestamp, (int, float)):
                timestamp_val = float(timestamp)
            elif hasattr(timestamp, 'timestamp'):
                # datetime object
                timestamp_val = timestamp.timestamp()
            else:
                timestamp_val = 0.0

            # 创建 Action 对象
            action = Action(
                action_type=row['action_type'],
                recording_mode=row['recording_mode'],
                url=row.get('url'),
                dom_element=dom_element,
                network_requests=network_requests if network_requests else None,
                parameters=parameters or {},
                timestamp=timestamp_val
            )

            return action

        except Exception as e:
            logger.error(f"转换单行数据失败: {e}")
            return None

    @staticmethod
    def _parse_json_field(json_data: Optional[str]) -> Optional[Dict]:
        """
        解析 JSON 字段

        Args:
            json_data: JSON 数据（字符串或已解析的字典）

        Returns:
            Dict: 解析后的字典，解析失败返回 None
        """
        if not json_data:
            return None

        # 如果已经是字典，直接返回
        if isinstance(json_data, dict):
            return json_data

        # 如果是字符串，进行解析
        if isinstance(json_data, str):
            if json_data.strip() == '':
                return None
            try:
                return json.loads(json_data)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON 解析失败: {e}")
                return None

        # 其他类型，返回 None
        return None

    @staticmethod
    def _parse_network_requests(network_data: Optional[str]) -> List[NetworkRequest]:
        """
        解析网络请求

        Args:
            network_data: 网络请求数据（可能是 JSON 字符串或列表）

        Returns:
            List[NetworkRequest]: 网络请求对象列表
        """
        if not network_data:
            return []

        try:
            # 如果已经是列表（DuckDB LIST 聚合结果）
            if isinstance(network_data, list):
                return [
                    ActionConverter._convert_dict_to_network_request(req)
                    for req in network_data
                    if req  # 过滤 None 值
                ]

            # 如果是 JSON 字符串
            if isinstance(network_data, str):
                if network_data.strip() == '':
                    return []
                data = json.loads(network_data)
            else:
                data = network_data

            # 处理不同的数据格式
            if isinstance(data, list):
                # 格式1: 直接是网络请求列表
                return [
                    ActionConverter._convert_dict_to_network_request(req)
                    for req in data
                    if req
                ]
            elif isinstance(data, dict):
                # 格式2: 包含在字典中
                if 'requests' in data:
                    return [
                        ActionConverter._convert_dict_to_network_request(req)
                        for req in data['requests']
                        if req
                    ]
                else:
                    # 将字典本身当作一个网络请求
                    return [ActionConverter._convert_dict_to_network_request(data)]

            return []

        except Exception as e:
            logger.warning(f"网络请求解析失败: {e}")
            return []

    @staticmethod
    def _convert_dict_to_network_request(req_dict: Dict) -> NetworkRequest:
        """
        将字典转换为 NetworkRequest 对象

        Args:
            req_dict: 请求数据字典

        Returns:
            NetworkRequest: 网络请求对象
        """
        # 处理 DuckDB 返回的 STRUCT 格式
        if isinstance(req_dict, dict):
            # 解析 JSON 字段（DuckDB 可能返回 JSON 字符串）
            parsed_dict = {}
            for key, value in req_dict.items():
                if key in ('request_headers', 'response_headers') and isinstance(value, str):
                    # 解析 headers JSON 字符串
                    try:
                        parsed_dict[key] = json.loads(value) if value else {}
                    except json.JSONDecodeError:
                        parsed_dict[key] = {}
                elif key in ('request_body', 'response_body') and isinstance(value, str):
                    # 保留 body 字符串
                    parsed_dict[key] = value if value else None
                else:
                    parsed_dict[key] = value

            # 提取需要的字段
            return NetworkRequest.from_dict(parsed_dict)
        else:
            # 如果已经是 NetworkRequest 对象
            return req_dict


class CompressionTestRunner:
    """执行压缩测试并收集结果"""

    def __init__(self):
        """初始化压缩测试运行器"""
        self.preprocessor = DataPreprocessor()

    def run_compression_test(
        self,
        actions: List[Action],
        compression_level: CompressionLevel
    ) -> Optional[PreprocessingResult]:
        """
        运行单个级别的压缩测试

        Args:
            actions: 原始操作列表
            compression_level: 压缩级别

        Returns:
            PreprocessingResult: 压缩结果
        """
        try:
            logger.info(f"开始测试 {compression_level.value} 级别压缩...")
            result = self.preprocessor.preprocess(
                actions,
                compression_level
            )
            logger.info(f"压缩完成: {len(actions)} -> {len(result.actions)}")
            return result

        except Exception as e:
            logger.error(f"压缩测试失败: {e}", exc_info=True)
            return None

    def compare_compression_levels(
        self,
        actions: List[Action],
        levels: Optional[List[CompressionLevel]] = None
    ) -> Dict[CompressionLevel, PreprocessingResult]:
        """
        对比所有压缩级别的效果

        Args:
            actions: 原始操作列表
            levels: 要测试的压缩级别列表，None 表示测试所有级别

        Returns:
            Dict: 压缩级别到结果的映射
        """
        if levels is None:
            levels = [
                CompressionLevel.NONE,
                CompressionLevel.CONSERVATIVE,
                CompressionLevel.MODERATE,
                CompressionLevel.AGGRESSIVE
            ]

        results = {}

        for level in levels:
            result = self.run_compression_test(actions, level)
            if result:
                results[level] = result

        return results


class ResultDisplay:
    """格式化和展示测试结果"""

    @staticmethod
    def display_session_list(sessions: List[Dict[str, Any]]):
        """
        显示录制会话列表

        Args:
            sessions: 录制会话列表
        """
        print("=" * 80)
        print("可用的录制会话")
        print("=" * 80)

        if not sessions:
            print("没有找到任何录制会话")
            return

        for i, session in enumerate(sessions, 1):
            # 处理时间格式（可能是 timestamp 或 datetime 对象）
            start_time_val = session['start_time']
            if isinstance(start_time_val, (int, float)):
                start_time = datetime.fromtimestamp(start_time_val).strftime('%Y-%m-%d %H:%M:%S')
            else:
                start_time = str(start_time_val)

            print(f"\n{i}. 录制ID: {session['recording_id']}")
            print(f"   模式: {session['recording_mode']}")
            print(f"   状态: {session['status']}")
            print(f"   操作数: {session['action_count']}")
            print(f"   开始时间: {start_time}")

        print("\n" + "=" * 80)

    @staticmethod
    def display_compression_summary(
        original_count: int,
        comparison_results: Dict[CompressionLevel, PreprocessingResult]
    ):
        """
        显示压缩对比摘要

        Args:
            original_count: 原始操作数量
            comparison_results: 压缩结果字典
        """
        print("\n" + "=" * 80)
        print("压缩级别对比摘要")
        print("=" * 80)
        print(
            f"{'级别':<16} {'原始操作':<10} {'压缩后':<10} {'关键操作':<10} "
            f"{'截图':<10} {'压缩率':<10}"
        )
        print("-" * 80)

        for level, result in comparison_results.items():
            compression_rate = (
                (original_count - len(result.actions)) / original_count * 100
                if original_count > 0 else 0
            )

            print(
                f"{level.value:<16} {original_count:<10} {len(result.actions):<10} "
                f"{len(result.key_actions):<10} {len(result.screenshots):<10} "
                f"{compression_rate:<10.1f}"
            )

        print("=" * 80)

    @staticmethod
    def display_detailed_comparison(
        original_actions: List[Action],
        compressed_results: Dict[CompressionLevel, PreprocessingResult],
        verbose: bool = False
    ):
        """
        显示详细压缩对比

        Args:
            original_actions: 原始操作列表
            compressed_results: 压缩结果字典
            verbose: 是否显示详细信息
        """
        # 原始数据概览
        print("\n" + "=" * 80)
        print("原始数据概览")
        print("=" * 80)
        print(f"总操作数: {len(original_actions)}")

        # 统计操作类型分布
        action_types = {}
        total_requests = 0
        actions_with_requests = 0

        for action in original_actions:
            action_type = action.action_type
            action_types[action_type] = action_types.get(action_type, 0) + 1

            if action.network_requests:
                total_requests += len(action.network_requests)
                actions_with_requests += 1

        print("操作类型分布:")
        for action_type, count in sorted(action_types.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {action_type}: {count}")

        print(f"\n网络请求: {total_requests} 个请求 (分布在 {actions_with_requests} 个操作中)")

        # 显示每个压缩级别的详细信息
        for level, result in compressed_results.items():
            print("\n" + "=" * 80)
            print(f"{level.value.upper()} 压缩级别详情")
            print("=" * 80)

            ResultDisplay._display_compression_stats(len(original_actions), result)

            if verbose and result.network_analysis:
                ResultDisplay._display_network_filter_stats(result)

        print("=" * 80)

    @staticmethod
    def _display_compression_stats(original_count: int, result: PreprocessingResult):
        """
        显示压缩统计信息

        Args:
            original_count: 原始操作数量
            result: 压缩结果
        """
        compression_rate = (
            (original_count - len(result.actions)) / original_count * 100
            if original_count > 0 else 0
        )

        print("\n压缩统计:")
        print(f"  原始操作: {original_count}")
        print(f"  压缩后操作: {len(result.actions)}")
        print(f"  关键操作: {len(result.key_actions)}")
        print(f"  截图数量: {len(result.screenshots)}")
        print(f"  压缩率: {compression_rate:.1f}%")

        # 从 metadata 中获取分析统计
        analysis_stats = result.metadata.get('analysis_stats', {})

        if analysis_stats:
            print("\n网络请求分析:")
            print(f"  总请求数: {analysis_stats.get('network_requests_analyzed', 0)}")
            print(f"  可复现API: {analysis_stats.get('replayable_apis', 0)}")
            print(f"  列表操作: {analysis_stats.get('list_operations', 0)}")

            if 'intelligent_filter' in analysis_stats:
                filter_stats = analysis_stats['intelligent_filter']
                print("\n智能过滤:")
                print(f"  总请求数: {filter_stats.get('total_requests', 0)}")
                print(f"  过滤掉: {filter_stats.get('filtered_out', 0)}")
                print(f"  保留: {filter_stats.get('meaningful_kept', 0)}")
                print(f"  过滤率: {filter_stats.get('filter_ratio', 'N/A')}")

            if 'recommendation_filter' in analysis_stats:
                rec_stats = analysis_stats['recommendation_filter']
                print("\n推荐内容过滤:")
                print(f"  总请求数: {rec_stats.get('total', 0)}")
                print(f"  过滤掉: {rec_stats.get('filtered', 0)}")
                print(f"  保留: {rec_stats.get('kept', 0)}")

    @staticmethod
    def _display_network_filter_stats(result: PreprocessingResult):
        """
        显示网络请求过滤统计

        Args:
            result: 预处理结果对象
        """
        if not result.network_analysis:
            return

        print("\n详细网络请求分析:")
        print(f"  网络请求数量: {len(result.network_analysis)}")

        # 统计可复现的 API
        replayable_count = sum(1 for n in result.network_analysis if hasattr(n, 'is_replayable') and n.is_replayable)
        print(f"  可复现 API: {replayable_count}")

        # 统计列表操作
        if result.list_analysis:
            print(f"  列表操作: {len(result.list_analysis)}")

    @staticmethod
    def display_retained_data_details(
        original_actions: List[Action],
        compressed_results: Dict[CompressionLevel, PreprocessingResult],
        show_level: CompressionLevel = None
    ):
        """
        显示压缩后保留的详细数据

        Args:
            original_actions: 原始操作列表
            compressed_results: 压缩结果字典
            show_level: 要显示的压缩级别，None 表示显示第一个
        """
        # 选择要显示的级别
        if show_level:
            target_level = show_level
            if target_level not in compressed_results:
                print(f"错误: 压缩级别 {show_level.value} 不在结果中")
                return
        else:
            # 显示第一个有压缩效果的级别
            for level in [CompressionLevel.MODERATE, CompressionLevel.CONSERVATIVE, CompressionLevel.NONE]:
                if level in compressed_results:
                    target_level = level
                    break
            else:
                print("错误: 没有可用的压缩结果")
                return

        result = compressed_results[target_level]

        print("\n" + "=" * 80)
        print(f"压缩后保留的详细数据 ({target_level.value.upper()} 级别)")
        print("=" * 80)

        # 显示保留的操作
        print(f"\n### 保留的操作 ({len(result.actions)} 个) ###\n")

        for i, processed_action in enumerate(result.actions, 1):
            original_action = processed_action.original_action
            print(f"{i}. 操作类型: {original_action.action_type}")
            print(f"   关键操作: {'是' if processed_action.is_key_action else '否'}")
            print(f"   时间戳: {original_action.timestamp}")

            if original_action.url:
                print(f"   URL: {original_action.url}")

            if original_action.parameters:
                print(f"   参数: {json.dumps(original_action.parameters, ensure_ascii=False, indent=6)}")

            # 显示网络请求
            if original_action.network_requests:
                print(f"   关联网络请求: {len(original_action.network_requests)} 个")
                for j, req in enumerate(original_action.network_requests, 1):
                    print(f"      {j}. [{req.method}] {req.url}")
                    if req.response_status:
                        print(f"         状态码: {req.response_status}")
                    if req.duration:
                        print(f"         耗时: {req.duration:.3f}s")
            else:
                print(f"   关联网络请求: 无")

            print()

        # 显示网络请求分析结果
        if result.network_analysis:
            print(f"\n### 网络请求分析 ({len(result.network_analysis)} 个) ###\n")

            for i, analysis in enumerate(result.network_analysis[:20], 1):  # 最多显示 20 个
                # 显示分析结果
                print(f"{i}. URL: {analysis.url if hasattr(analysis, 'url') else 'N/A'}")
                print(f"   方法: {analysis.method if hasattr(analysis, 'method') else 'N/A'}")
                print(f"   可复现: {'是' if hasattr(analysis, 'is_replayable') and analysis.is_replayable else '否'}")

                if hasattr(analysis, 'replay_strategy') and analysis.replay_strategy:
                    print(f"   复现策略: {analysis.replay_strategy}")

                if hasattr(analysis, 'response_structure') and analysis.response_structure:
                    print(f"   响应结构: {analysis.response_structure}")

                print()

            if len(result.network_analysis) > 20:
                print(f"... 还有 {len(result.network_analysis) - 20} 个网络请求分析结果未显示\n")

        # 显示列表操作分析
        if result.list_analysis:
            print(f"\n### 列表操作分析 ({len(result.list_analysis)} 个) ###\n")

            for i, list_op in enumerate(result.list_analysis, 1):
                print(f"{i}. 列表操作")
                if hasattr(list_op, 'list_url') and list_op.list_url:
                    print(f"   列表 URL: {list_op.list_url}")
                if hasattr(list_op, 'suggested_strategy') and list_op.suggested_strategy:
                    print(f"   推荐策略: {list_op.suggested_strategy}")
                print()

        print("=" * 80)


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='数据压缩功能演示测试脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 列出所有可用的录制会话
  %(prog)s --list

  # 测试指定会话（所有压缩级别）
  %(prog)s --recording-id rec-20250205-103600 --verbose

  # 测试单个压缩级别
  %(prog)s --recording-id rec-20250205-103600 --level moderate
        """
    )

    parser.add_argument(
        '--db-path',
        type=str,
        default='data/mexemplar.duckdb',
        help='DuckDB 数据库文件路径 (默认: data/mexemplar.duckdb)'
    )

    parser.add_argument(
        '--list',
        action='store_true',
        help='列出所有可用的录制会话'
    )

    parser.add_argument(
        '--recording-id',
        type=str,
        help='要测试的录制会话 ID'
    )

    parser.add_argument(
        '--level',
        type=str,
        choices=['none', 'conservative', 'moderate', 'aggressive'],
        help='压缩级别 (默认: 测试所有级别)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='显示详细信息'
    )

    parser.add_argument(
        '--show-details',
        action='store_true',
        help='显示压缩后保留的详细数据'
    )

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_arguments()

    # 创建数据库读取器
    reader = DuckDBReader(args.db_path)

    if not reader.connect():
        logger.error("无法连接到数据库")
        return 1

    try:
        # 列出所有会话
        sessions = reader.list_recording_sessions()

        if args.list:
            ResultDisplay.display_session_list(sessions)
            return 0

        # 检查是否指定了录制会话 ID
        if not args.recording_id:
            logger.error("请使用 --recording-id 指定要测试的录制会话，或使用 --list 查看所有会话")
            return 1

        # 查找指定的录制会话
        session = None
        for s in sessions:
            if s['recording_id'] == args.recording_id:
                session = s
                break

        if not session:
            logger.error(f"未找到录制会话: {args.recording_id}")
            return 1

        print(f"\n选择会话: {args.recording_id}")
        print(f"操作数: {session['action_count']}")

        # 读取操作数据
        duckdb_actions = reader.get_actions_by_recording_id(args.recording_id)

        if not duckdb_actions:
            logger.error(f"会话 {args.recording_id} 中没有操作数据")
            return 1

        # 转换为 Action 对象
        print("\n转换数据为 Action 对象...")
        actions = ActionConverter.convert_from_duckdb(duckdb_actions)

        if not actions:
            logger.error("没有成功转换任何操作")
            return 1

        # 运行压缩测试
        print("\n开始压缩测试...")
        runner = CompressionTestRunner()

        # 确定要测试的压缩级别
        if args.level:
            level = CompressionLevel(args.level)
            results = {}
            result = runner.run_compression_test(actions, level)
            if result:
                results[level] = result
        else:
            results = runner.compare_compression_levels(actions)

        if not results:
            logger.error("压缩测试失败")
            return 1

        # 显示结果
        print("\n测试完成!\n")

        # 显示摘要
        ResultDisplay.display_compression_summary(len(actions), results)

        # 显示详细信息
        ResultDisplay.display_detailed_comparison(actions, results, args.verbose)

        # 显示保留的详细数据（如果请求）
        if args.show_details:
            show_level = CompressionLevel(args.level) if args.level else None
            ResultDisplay.display_retained_data_details(actions, results, show_level)

        return 0

    except Exception as e:
        logger.error(f"程序执行失败: {e}", exc_info=True)
        return 1

    finally:
        reader.close()


if __name__ == '__main__':
    sys.exit(main())
