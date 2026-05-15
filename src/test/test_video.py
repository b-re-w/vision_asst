"""FrameBuffer behavior tests."""

from __future__ import annotations

from vision_asst.streaming.video import FrameBuffer


def test_frames_evicted_outside_window() -> None:
    fb = FrameBuffer(window_ms=1000)
    fb.add(b"old", ts_ms=0)
    fb.add(b"new", ts_ms=2000)
    # Force eviction by adding a future-stamped frame
    fb.add(b"newer", ts_ms=2100)
    seen = [jpg for _, jpg in list(fb)]
    assert b"old" not in seen


def test_recent_returns_at_most_max_n() -> None:
    fb = FrameBuffer(window_ms=10_000)
    for i in range(10):
        fb.add(f"f{i}".encode())
    out = fb.recent(max_n=4)
    assert len(out) <= 4


def test_recent_returns_empty_when_buffer_empty() -> None:
    fb = FrameBuffer()
    assert fb.recent(max_n=4) == []


def test_recent_includes_latest_frame() -> None:
    fb = FrameBuffer(window_ms=10_000)
    for i in range(6):
        fb.add(f"f{i}".encode())
    out = fb.recent(max_n=3)
    assert b"f5" in out


def test_clear_empties_buffer() -> None:
    fb = FrameBuffer()
    fb.add(b"x")
    fb.clear()
    assert len(fb) == 0
    assert fb.recent(max_n=1) == []
