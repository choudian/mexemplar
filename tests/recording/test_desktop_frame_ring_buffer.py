from src.recording.desktop.frame_ring_buffer import FrameRingBuffer, FrameSample


def test_desktop_frame_ring_buffer_fifo_and_window():
    buffer = FrameRingBuffer(capacity=3)
    for timestamp in [0.0, 1.0, 2.0, 3.0]:
        buffer.append(FrameSample(timestamp=timestamp))

    assert [frame.timestamp for frame in buffer.frames_for_action(2.0)] == [1.0, 2.0, 3.0]
    assert [frame.timestamp for frame in buffer.frames_for_action(0.2)] == [1.0, 2.0]


def test_desktop_frame_ring_buffer_keeps_monitor_windows_separate():
    buffer = FrameRingBuffer(capacity=2)
    buffer.append(FrameSample(timestamp=1.0, monitor_index=0))
    buffer.append(FrameSample(timestamp=1.1, monitor_index=1))
    buffer.append(FrameSample(timestamp=1.2, monitor_index=0))
    buffer.append(FrameSample(timestamp=1.3, monitor_index=1))

    assert [frame.timestamp for frame in buffer.frames_for_action(1.2, monitor_index=0)] == [
        1.0,
        1.2,
    ]
    assert [frame.timestamp for frame in buffer.frames_for_action(1.2, monitor_index=1)] == [
        1.1,
        1.3,
    ]
