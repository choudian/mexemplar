# 数据压缩功能演示测试脚本

## 概述

`test_compression_demo.py` 是一个独立的测试脚本，用于演示数据压缩功能的完整流程。

## 功能特性

1. **数据库读取**: 从 DuckDB 读取录制会话和操作数据
2. **数据转换**: 将 DuckDB 数据转换为 Action 对象
3. **压缩测试**: 执行不同级别的数据压缩
4. **结果展示**: 展示压缩前后的详细对比

## 使用方法

### 1. 列出所有可用的录制会话

```bash
uv run python tests/integration/test_compression_demo.py --list
```

**输出示例**:
```
================================================================================
可用的录制会话
================================================================================

1. 录制ID: ef630ed7-0519-4975-b1a9-b7dbc044287e
   模式: browser
   状态: completed
   操作数: 6
   开始时间: 2026-02-05 10:35:53.692085
```

### 2. 测试指定会话（所有压缩级别）

```bash
uv run python tests/integration/test_compression_demo.py \
    --recording-id <recording-id>
```

**输出包括**:
- 压缩级别对比摘要
- 原始数据概览
- 每个压缩级别的详细统计
- 网络请求分析
- 智能过滤统计

### 3. 测试单个压缩级别

```bash
uv run python tests/integration/test_compression_demo.py \
    --recording-id <recording-id> \
    --level moderate
```

**可用的压缩级别**:
- `none`: 不压缩
- `conservative`: 保守压缩（60-70%）
- `moderate`: 适中压缩（70-80%）
- `aggressive`: 激进压缩（80-90%）

### 4. 显示详细信息

添加 `--verbose` 或 `-v` 参数可以显示更详细的网络请求分析：

```bash
uv run python tests/integration/test_compression_demo.py \
    --recording-id <recording-id> \
    --verbose
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--db-path` | DuckDB 数据库文件路径 | `data/mexemplar.duckdb` |
| `--list` | 列出所有可用的录制会话 | - |
| `--recording-id` | 要测试的录制会话 ID | - |
| `--level` | 压缩级别（none/conservative/moderate/aggressive） | 测试所有级别 |
| `--verbose`, `-v` | 显示详细信息 | - |

## 输出示例

### 压缩级别对比摘要

```
================================================================================
压缩级别对比摘要
================================================================================
级别               原始操作     压缩后      关键操作     截图         压缩率
--------------------------------------------------------------------------------
none             6          6          6          0          0.0
conservative     6          4          4          0          33.3
moderate         6          2          2          0          66.7
aggressive       6          2          2          0          66.7
================================================================================
```

### 详细压缩统计

```
================================================================================
MODERATE 压缩级别详情
================================================================================

压缩统计:
  原始操作: 6
  压缩后操作: 2
  关键操作: 2
  截图数量: 0
  压缩率: 66.7%

网络请求分析:
  总请求数: 10
  可复现API: 10
  列表操作: 0

智能过滤:
  总请求数: 10
  过滤掉: 0
  保留: 10
  过滤率: 0.0%

推荐内容过滤:
  总请求数: 10
  过滤掉: 0
  保留: 10
```

## 架构说明

脚本包含四个核心类：

### 1. DuckDBReader
- 职责: 从 DuckDB 读取录制数据
- 关键方法:
  - `list_recording_sessions()`: 列出所有录制会话
  - `get_actions_by_recording_id()`: 获取指定会话的所有操作

### 2. ActionConverter
- 职责: 将 DuckDB 数据转换为 Action 对象
- 关键方法:
  - `convert_from_duckdb()`: 批量转换
  - `_parse_network_requests()`: 解析网络请求（支持 JSON 字符串和列表）
  - `_convert_dict_to_network_request()`: 处理 DuckDB STRUCT 格式

### 3. CompressionTestRunner
- 职责: 执行压缩测试并收集结果
- 关键方法:
  - `run_compression_test()`: 运行单个级别测试
  - `compare_compression_levels()`: 对比所有压缩级别

### 4. ResultDisplay
- 职责: 格式化和展示测试结果
- 关键方法:
  - `display_session_list()`: 显示录制会话列表
  - `display_compression_summary()`: 显示压缩对比摘要
  - `display_detailed_comparison()`: 显示详细对比

## 注意事项

1. **数据库路径**: 默认使用 `data/mexemplar.duckdb`，如果数据库文件位置不同，请使用 `--db-path` 参数指定

2. **Unicode 编码**: 脚本中的日志输出包含 emoji 字符，在 Windows GBK 编码环境下可能会显示编码错误，但不影响功能

3. **网络请求解析**: DuckDB 的 JSON 字段会被转换为字符串，脚本会自动解析这些 JSON 字段

4. **时间戳处理**: 脚本会自动将 DuckDB 的 TIMESTAMP 类型转换为 Unix 时间戳（float）

## 故障排除

### 错误: 数据库文件不存在
```
ERROR - 数据库文件不存在: data/mexemplar.duckdb
```

**解决方案**: 使用 `--db-path` 参数指定正确的数据库文件路径

### 错误: 未找到录制会话
```
ERROR - 未找到录制会话: <recording-id>
```

**解决方案**: 使用 `--list` 参数查看所有可用的录制会话

### 错误: 会话中没有操作数据
```
ERROR - 会话 <recording-id> 中没有操作数据
```

**解决方案**: 该录制会话可能是空的，尝试选择其他会话

## 开发指南

### 添加新的压缩级别

1. 在 `src/business/ai/data_preprocessor.py` 中的 `CompressionLevel` 枚举中添加新级别
2. 更新命令行参数解析中的 `choices` 列表
3. 在 `CompressionTestRunner` 中实现相应的压缩逻辑

### 扩展输出格式

1. 在 `ResultDisplay` 类中添加新的显示方法
2. 在主函数中调用新的显示方法
3. 更新输出示例文档

## 相关文档

- [数据压缩功能文档](../../docs/features/compression-model-configuration.md)
- [网络请求智能过滤文档](../../docs/features/network-request-intelligent-filter.md)
- [开发路线图](../../docs/local/development/development_roadmap.md)
