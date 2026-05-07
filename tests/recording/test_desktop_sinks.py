from PIL import Image

from src.recording.desktop.clip_sink import ClipSink
from src.recording.desktop.frame_ring_buffer import FrameSample
from src.recording.desktop.png_sink import PngSink


def test_png_sink_writes_native_png_frames(tmp_path):
    sink = PngSink(tmp_path)
    frame = FrameSample(timestamp=1.0, image_data=Image.new("RGB", (10, 5), "red"))

    paths = sink.write_frames("act-1", [frame])

    assert paths[0].name == "frame_001.png"
    assert Image.open(paths[0]).size == (10, 5)


def test_clip_sink_respects_enable_clip_false(tmp_path):
    sink = ClipSink(tmp_path, enable_clip=False)

    result = sink.write_clip("act-1", [object()])

    assert result.has_clip is False
    assert result.reason == "disabled"
    assert sink.clip_total == 0
