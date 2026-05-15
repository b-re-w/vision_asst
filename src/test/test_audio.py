"""Tests for AudioRingBuffer and PCM helpers."""

from __future__ import annotations

import numpy as np
import pytest

from vision_asst.streaming.audio import AudioRingBuffer, bytes_to_int16, int16_to_bytes


def test_bytes_int16_round_trip() -> None:
    arr = np.array([1, -1, 32000, -32000], dtype=np.int16)
    assert np.array_equal(bytes_to_int16(int16_to_bytes(arr)), arr)


def test_bytes_to_int16_rejects_odd_length() -> None:
    with pytest.raises(ValueError):
        bytes_to_int16(b"\x01\x02\x03")


def test_ring_buffer_appends_and_reports_duration() -> None:
    buf = AudioRingBuffer(sample_rate=16000, max_ms=1000)
    buf.append_bytes(int16_to_bytes(np.zeros(1600, dtype=np.int16)))  # 100 ms
    assert buf.samples == 1600
    assert buf.duration_ms == 100


def test_ring_buffer_trims_to_capacity() -> None:
    buf = AudioRingBuffer(sample_rate=16000, max_ms=100)  # 1600 samples
    buf.append(np.arange(2000, dtype=np.int16))
    assert buf.samples == 1600
    # the most recent samples should be retained
    last = buf.read_window(50)
    assert last[-1] == np.int16(1999)


def test_take_all_clears_buffer() -> None:
    buf = AudioRingBuffer(sample_rate=16000)
    buf.append(np.ones(500, dtype=np.int16))
    out = buf.take_all()
    assert out.size == 500
    assert buf.samples == 0


def test_read_window_smaller_than_buffer() -> None:
    buf = AudioRingBuffer(sample_rate=16000)
    buf.append(np.arange(3200, dtype=np.int16))  # 200 ms
    win = buf.read_window(50)  # 800 samples
    assert win.size == 800
    assert win[0] == np.int16(2400)


def test_read_window_larger_than_buffer() -> None:
    buf = AudioRingBuffer(sample_rate=16000)
    buf.append(np.arange(160, dtype=np.int16))  # 10 ms
    win = buf.read_window(1000)
    assert win.size == 160
