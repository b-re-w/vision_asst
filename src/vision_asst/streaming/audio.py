"""PCM16 audio ring buffer used to accumulate inbound speech for a turn."""

from __future__ import annotations

import numpy as np


def bytes_to_int16(b: bytes) -> np.ndarray:
    """Convert little-endian PCM16 bytes to a contiguous int16 array."""
    if len(b) % 2 != 0:
        raise ValueError("PCM16 bytes must have even length")
    return np.frombuffer(b, dtype="<i2").astype(np.int16, copy=False)


def int16_to_bytes(x: np.ndarray) -> bytes:
    """Convert an int16 array back to little-endian PCM16 bytes."""
    if x.dtype != np.int16:
        x = x.astype(np.int16)
    return x.tobytes()


class AudioRingBuffer:
    """Append-only int16 buffer with millisecond-aware accessors.

    Capacity is enforced by trimming from the front: when the buffer would
    grow past ``max_ms`` of audio, the oldest samples are discarded.
    """

    def __init__(self, sample_rate: int, max_ms: int = 30_000) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self.sample_rate = sample_rate
        self.max_samples = int(sample_rate * max_ms / 1000)
        self._buf: np.ndarray = np.zeros(0, dtype=np.int16)

    # ------------------------------------------------------------------ ops
    def append_bytes(self, b: bytes) -> None:
        self.append(bytes_to_int16(b))

    def append(self, samples: np.ndarray) -> None:
        if samples.dtype != np.int16:
            samples = samples.astype(np.int16)
        if samples.size == 0:
            return
        self._buf = np.concatenate([self._buf, samples])
        if self._buf.size > self.max_samples:
            self._buf = self._buf[-self.max_samples :]

    def take_all(self) -> np.ndarray:
        """Return all buffered samples and clear the buffer."""
        out = self._buf
        self._buf = np.zeros(0, dtype=np.int16)
        return out

    def clear(self) -> None:
        self._buf = np.zeros(0, dtype=np.int16)

    def read_window(self, ms: int) -> np.ndarray:
        n = int(self.sample_rate * ms / 1000)
        if n >= self._buf.size:
            return self._buf.copy()
        return self._buf[-n:].copy()

    @property
    def duration_ms(self) -> int:
        return int(self._buf.size * 1000 / self.sample_rate)

    @property
    def samples(self) -> int:
        return int(self._buf.size)


__all__ = ["AudioRingBuffer", "bytes_to_int16", "int16_to_bytes"]
