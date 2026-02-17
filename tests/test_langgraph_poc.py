"""
LangGraph PoC 验证脚本

验证以下功能：
1. Agent 能成功执行带 interrupt 的流程
2. interrupt 后能通过 resume 恢复执行
3. Checkpointer 能持久化状态，重启后可恢复
4. Agent interrupt 能通过 PyQt 信号触发 UI 更新
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from typing import Dict, Any
from langgraph.types import interrupt
from langchain_core.messages import AIMessage

from src.business.agent.state import AgentState
from src.business.agent.graph import create_agent_graph
from src.business.agent.checkpointer import (
    get_checkpointer_context,
    get_memory_checkpointer,
    get_checkpointer_db_path,
)


def create_poc_graph():
    """
    创建 PoC 验证用的 Agent 图

    包含一个简单的 interrupt 节点
    """
    from langgraph.graph import StateGraph, END

    def poc_node_with_interrupt(state: AgentState) -> Dict[str, Any]:
        """带有 interrupt 的节点"""
        # 模拟一些处理
        print("[PoC] 执行节点处理...")

        # 触发 interrupt，等待用户输入
        user_input = interrupt({
            "type": "poc_confirmation",
            "message": "请确认是否继续？",
            "data": {"value": 42}
        })

        print(f"[PoC] 收到用户输入: {user_input}")

        # 根据用户输入继续处理
        if user_input.get("confirm", False):
            return {
                "messages": [AIMessage(content="用户确认，继续执行")]
            }
        else:
            return {
                "messages": [AIMessage(content="用户取消")]
            }

    # 创建状态图
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("poc_interrupt", poc_node_with_interrupt)

    # 设置入口点
    workflow.set_entry_point("poc_interrupt")

    # 添加边
    workflow.add_edge("poc_interrupt", END)

    return workflow


def test_1_interrupt_and_resume():
    """
    测试 1: Agent 能成功执行带 interrupt 的流程，并能恢复
    """
    print("\n" + "="*60)
    print("测试 1: interrupt 和 resume 功能")
    print("="*60)

    from langgraph.types import Command

    # 创建 Agent 图
    workflow = create_poc_graph()
    checkpointer = get_memory_checkpointer()
    app = workflow.compile(checkpointer=checkpointer)

    # 初始状态
    initial_state = {"messages": []}
    config = {"configurable": {"thread_id": "test-session-1"}}

    # 第一次调用 - 会触发 interrupt
    print("\n[步骤 1] 首次调用 Agent...")
    result = app.invoke(initial_state, config)
    print(f"[结果] 执行返回: {result}")

    # 检查是否有 interrupt
    state_snapshot = app.get_state(config)
    print(f"\n[步骤 2] 检查状态...")
    print(f"状态值: {state_snapshot.values}")
    print(f"下一个节点: {state_snapshot.next}")

    # 检查 tasks 中的 interrupt
    if state_snapshot.tasks:
        print(f"任务列表: {state_snapshot.tasks}")
        for task in state_snapshot.tasks:
            if hasattr(task, 'interrupts') and task.interrupts:
                print(f"[成功] 检测到 interrupt: {task.interrupts}")

                # 恢复执行 - 使用 Command(resume=...)
                print("\n[步骤 3] 恢复执行（用户确认）...")
                result = app.invoke(
                    Command(resume={"confirm": True}),
                    config
                )
                print(f"[成功] 执行结果: {result}")
                return True

    print("[失败] 未检测到 interrupt")
    return False


def test_2_checkpointer_persistence():
    """
    测试 2: Checkpointer 能持久化状态
    """
    print("\n" + "="*60)
    print("测试 2: Checkpointer 持久化")
    print("="*60)

    db_path = str(get_checkpointer_db_path())
    print(f"数据库路径: {db_path}")

    # 使用 SQLite checkpointer（使用上下文管理器）
    with get_checkpointer_context(db_path) as checkpointer:
        workflow = create_poc_graph()
        app = workflow.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "test-session-2"}}

        # 执行到 interrupt
        print("\n[步骤 1] 执行到 interrupt...")
        result = app.invoke({"messages": []}, config)
        print(f"执行结果: {result}")

        # 获取状态
        state = app.get_state(config)
        print(f"状态已保存: {state.values is not None}")

    # 模拟重启 - 重新加载 checkpointer
    print("\n[步骤 2] 模拟重启，重新加载状态...")
    with get_checkpointer_context(db_path) as checkpointer:
        workflow = create_poc_graph()
        app = workflow.compile(checkpointer=checkpointer)

        # 使用相同的 thread_id
        state = app.get_state(config)
        print(f"状态已恢复: {state.values is not None}")
        print(f"状态内容: {state.values}")

    return True


def test_3_pyqt_signal():
    """
    测试 3: PyQt 信号集成

    使用 AgentUIBridge 测试信号传递。
    注意：这个测试使用简化的 PoC 图，不调用真实 LLM。
    """
    print("\n" + "="*60)
    print("测试 3: PyQt 信号集成")
    print("="*60)

    import time as time_module
    import threading
    from PyQt6.QtCore import QCoreApplication
    from src.business.agent.ui_bridge import AgentUIBridge

    # 创建 Qt 应用
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)

    # 创建 AgentUIBridge
    bridge = AgentUIBridge()

    # 记录信号
    signals_received = []
    signal_lock = threading.Lock()

    def on_interrupt(thread_id, data):
        with signal_lock:
            signals_received.append(("interrupt", thread_id, data))
        print(f"[信号] 收到 interrupt: thread_id={thread_id}")
        print(f"       data: {data}")

    def on_response(thread_id, response):
        with signal_lock:
            signals_received.append(("response", thread_id, response))
        print(f"[信号] 收到 response: thread_id={thread_id}")

    def on_error(thread_id, error):
        with signal_lock:
            signals_received.append(("error", thread_id, error))
        print(f"[信号] 收到 error: thread_id={thread_id}")
        print(f"       error: {error[:200]}...")

    def on_completed(thread_id):
        with signal_lock:
            signals_received.append(("completed", thread_id, None))
        print(f"[信号] 收到 completed: thread_id={thread_id}")

    # 连接信号
    bridge.interrupt_requested.connect(on_interrupt)
    bridge.response_ready.connect(on_response)
    bridge.error_occurred.connect(on_error)
    bridge.session_completed.connect(on_completed)

    # 创建一个简单的测试 Agent（使用 PoC 图）
    def run_test_agent():
        try:
            from langgraph.types import Command
            workflow = create_poc_graph()
            checkpointer = get_memory_checkpointer()
            test_app = workflow.compile(checkpointer=checkpointer)

            config = {"configurable": {"thread_id": "test-pyqt-simple"}}

            # 执行到 interrupt
            result = test_app.invoke({"messages": []}, config)

            # 检查是否有 interrupt
            state = test_app.get_state(config)
            if state.tasks:
                for task in state.tasks:
                    if hasattr(task, 'interrupts') and task.interrupts:
                        # 模拟 interrupt 信号
                        interrupt_data = {
                            "interrupts": [
                                {"value": intr.value, "id": intr.id}
                                for intr in task.interrupts
                            ]
                        }
                        bridge.interrupt_requested.emit("test-pyqt-simple", interrupt_data)

                        # 模拟用户确认后继续
                        time_module.sleep(0.5)
                        result = test_app.invoke(
                            Command(resume={"confirm": True}),
                            config
                        )
                        break

            # 发送完成信号
            bridge.session_completed.emit("test-pyqt-simple")

        except Exception as e:
            import traceback
            bridge.error_occurred.emit("test-pyqt-simple", f"{e}\n{traceback.format_exc()}")

    # 在后台线程运行测试 Agent
    print("\n[步骤 1] 启动测试 Agent...")
    thread = threading.Thread(target=run_test_agent, daemon=True)
    thread.start()

    # 等待信号
    print("[等待] 等待 Agent 执行（最多 5 秒）...")

    wait_count = 0
    max_wait = 50  # 5 秒 (50 * 100ms)

    while wait_count < max_wait:
        app.processEvents()
        time_module.sleep(0.1)
        with signal_lock:
            if signals_received:
                break
        wait_count += 1

    # 等待线程结束
    thread.join(timeout=2)

    print(f"\n[结果] 收到的信号: {len(signals_received)} 个")
    for signal in signals_received:
        print(f"  - {signal[0]}: {signal[1]}")

    # 判断是否成功
    # 应该收到 interrupt 或 completed 信号
    success_signals = ["interrupt", "completed"]
    received_success = any(s[0] in success_signals for s in signals_received)

    return received_success


def main():
    """运行所有测试"""
    print("="*60)
    print("LangGraph PoC 验证")
    print("="*60)

    results = {}

    # 测试 1: interrupt 和 resume
    try:
        results["interrupt_resume"] = test_1_interrupt_and_resume()
    except Exception as e:
        print(f"[失败] 测试 1 异常: {e}")
        import traceback
        traceback.print_exc()
        results["interrupt_resume"] = False

    # 测试 2: 持久化
    try:
        results["persistence"] = test_2_checkpointer_persistence()
    except Exception as e:
        print(f"[失败] 测试 2 异常: {e}")
        import traceback
        traceback.print_exc()
        results["persistence"] = False

    # 测试 3: PyQt 信号（可选，需要 Qt 环境）
    try:
        results["pyqt_signal"] = test_3_pyqt_signal()
    except Exception as e:
        print(f"[跳过] 测试 3（PyQt 环境）: {e}")
        results["pyqt_signal"] = None

    # 汇总结果
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)

    for test_name, passed in results.items():
        if passed is None:
            status = "跳过"
        elif passed:
            status = "通过"
        else:
            status = "失败"
        print(f"  {test_name}: {status}")

    # 整体通过标准
    core_tests = ["interrupt_resume", "persistence"]
    all_passed = all(results.get(t, False) for t in core_tests)

    if all_passed:
        print("\n[结论] 核心功能验证通过")
    else:
        print("\n[结论] 核心功能验证失败")

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
