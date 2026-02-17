"""
浏览器录制功能集成测试

测试 main.py 中浏览器录制的集成是否正常工作
"""

import pytest
from unittest.mock import Mock, patch
from src.recording.recorder import RecordingSession


class TestBrowserRecordingIntegration:
    """测试浏览器录制集成"""

    @patch("src.recording.recorder.Recorder")
    @patch("src.main.input")
    @patch("src.main.confirm")
    def test_handle_browser_recording_success(
        self, mock_confirm, mock_input, mock_recorder_class, config
    ):
        """测试浏览器录制成功场景"""
        from src.main import handle_browser_recording

        # Mock 配置
        config.get = Mock(return_value=None)

        # Mock confirm（不输入自定义 URL）
        mock_confirm_obj = Mock()
        mock_confirm_obj.ask = Mock(return_value=False)
        mock_confirm.return_value = mock_confirm_obj

        # Mock Recorder 实例
        mock_recorder = Mock()
        mock_recorder_class.return_value = mock_recorder

        # Mock 录制过程
        mock_recorder.start_recording.return_value = "test-recording-id"

        # Mock 录制会话
        mock_session = RecordingSession(
            recording_id="test-recording-id",
            status="stopped",
            recording_mode="browser",
            start_time=1000.0,
            end_time=1010.0,
        )
        mock_session.metadata = {"action_count": 5, "queue_file": "/path/to/queue.jsonl"}
        mock_recorder.stop_recording.return_value = mock_session

        # 执行测试
        handle_browser_recording(config)

        # 验证调用
        mock_recorder_class.assert_called_once_with(recording_mode="browser")
        mock_recorder.start_recording.assert_called_once_with(start_url=None)
        mock_recorder.stop_recording.assert_called_once()
        mock_recorder.close.assert_called_once()

    @patch("src.recording.recorder.Recorder")
    @patch("src.main.input")
    def test_handle_browser_recording_with_custom_url(
        self, mock_input, mock_recorder_class, config
    ):
        """测试带自定义 URL 的浏览器录制"""
        from src.main import handle_browser_recording

        # Mock 配置
        config.get = Mock(return_value=None)

        # Mock input 返回 True（输入自定义 URL）
        with patch("src.main.text") as mock_text:
            with patch("src.main.confirm") as mock_confirm:
                mock_confirm.return_value.ask = Mock(return_value=True)
                mock_text.return_value.ask = Mock(return_value="https://example.com")

                # Mock Recorder 实例
                mock_recorder = Mock()
                mock_recorder_class.return_value = mock_recorder
                mock_recorder.start_recording.return_value = "test-recording-id"
                mock_recorder.stop_recording.return_value = None

                # 执行测试
                handle_browser_recording(config)

                # 验证使用了自定义 URL
                mock_recorder.start_recording.assert_called_once_with(
                    start_url="https://example.com"
                )

    @patch("src.recording.recorder.Recorder")
    @patch("src.main.input")
    @patch("src.main.confirm")
    def test_handle_browser_recording_failure(
        self, mock_confirm, mock_input, mock_recorder_class, config
    ):
        """测试浏览器录制失败场景"""
        from src.main import handle_browser_recording

        # Mock 配置
        config.get = Mock(return_value=None)

        # Mock confirm（不输入自定义 URL）
        mock_confirm_obj = Mock()
        mock_confirm_obj.ask = Mock(return_value=False)
        mock_confirm.return_value = mock_confirm_obj

        # Mock Recorder 抛出异常
        mock_recorder_class.side_effect = Exception("启动失败")

        # 执行测试（应该不抛出异常）
        handle_browser_recording(config)

        # 验证调用了 Recorder 构造函数
        assert mock_recorder_class.call_count == 1

    def test_simple_handle_browser_recording_success(self, config):
        """测试简单模式的浏览器录制"""
        from src.main import simple_handle_browser_recording

        # Mock 配置
        config.get = Mock(return_value=None)

        with patch("src.main.input", return_value=""):
            with patch("src.recording.recorder.Recorder") as mock_recorder_class:
                # Mock Recorder 实例
                mock_recorder = Mock()
                mock_recorder_class.return_value = mock_recorder
                mock_recorder.start_recording.return_value = "test-recording-id"

                # Mock 录制会话
                mock_session = RecordingSession(
                    recording_id="test-recording-id",
                    status="stopped",
                    recording_mode="browser",
                    start_time=1000.0,
                    end_time=1010.0,
                )
                mock_session.metadata = {"action_count": 5}
                mock_recorder.stop_recording.return_value = mock_session

                # 执行测试
                simple_handle_browser_recording(config)

                # 验证调用
                mock_recorder_class.assert_called_once_with(recording_mode="browser")
                mock_recorder.start_recording.assert_called_once()
                mock_recorder.stop_recording.assert_called_once()
                mock_recorder.close.assert_called_once()


@pytest.fixture
def config():
    """Mock 配置对象"""
    mock_config = Mock()
    mock_config.get = Mock(return_value=None)
    return mock_config
