"""Time-windowed JPEG frame buffer for the active turn."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable


def now_ms() -> int:
    return int(time.monotonic() * 1000)


class FrameBuffer:
    """Deque of ``(timestamp_ms, jpeg_bytes)`` pairs.

    ``add`` evicts frames older than ``window_ms``. ``recent`` returns up to
    ``max_n`` frames evenly sampled across the most recent ``window_ms``
    window so the model gets temporally diverse context, not a burst from
    the last 100 ms.
    """

    def __init__(self, window_ms: int = 4000, max_buffered: int = 64) -> None:
        if window_ms <= 0 or max_buffered <= 0:
            raise ValueError("window_ms and max_buffered must be positive")
        self.window_ms = window_ms
        self._buf: deque[tuple[int, bytes]] = deque(maxlen=max_buffered)

    def add(self, jpeg: bytes, ts_ms: int | None = None) -> None:
        ts = ts_ms if ts_ms is not None else now_ms()
        self._buf.append((ts, jpeg))
        self._evict(ts)

    def _evict(self, current_ms: int) -> None:
        cutoff = current_ms - self.window_ms
        while self._buf and self._buf[0][0] < cutoff:
            self._buf.popleft()

    def recent(self, max_n: int, window_ms: int | None = None) -> list[bytes]:
        if max_n <= 0 or not self._buf:
            return []
        cur = now_ms()
        cutoff = cur - (window_ms or self.window_ms)
        eligible = [(ts, jpg) for ts, jpg in self._buf if ts >= cutoff]
        if not eligible:
            return []
        if len(eligible) <= max_n:
            return [jpg for _, jpg in eligible]
        # Even sampling across eligible frames, keeping the latest one.
        step = (len(eligible) - 1) / (max_n - 1) if max_n > 1 else 0
        idxs = [round(i * step) for i in range(max_n)] if max_n > 1 else [len(eligible) - 1]
        # de-duplicate while preserving order
        seen: set[int] = set()
        out: list[bytes] = []
        for idx in idxs:
            if idx in seen:
                continue
            seen.add(idx)
            out.append(eligible[idx][1])
        return out

    def __len__(self) -> int:
        return len(self._buf)

    def clear(self) -> None:
        self._buf.clear()

    def __iter__(self) -> Iterable[tuple[int, bytes]]:
        return iter(self._buf)


__all__ = ["FrameBuffer", "now_ms"]
