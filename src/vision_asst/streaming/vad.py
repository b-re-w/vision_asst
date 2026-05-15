"""Voice activity detection wrapper around ``webrtcvad``.

Emits high-level events (``voiced_start``, ``utterance_end``) used by the
session orchestrator to drive turn detection and barge-in.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

import webrtcvad


class VadEvent(StrEnum):
    VOICED_START = "voiced_start"
    UTTERANCE_END = "utterance_end"


@dataclass(slots=True)
class VadConfig:
    sample_rate: int = 16000
    frame_ms: int = 20
    aggressiveness: int = 2
    min_voiced_ms: int = 250
    silence_ms: int = 300

    @property
    def frame_bytes(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000) * 2


class VadDetector:
    """Stateful VAD that turns raw PCM bytes into utterance-level events."""

    def __init__(self, cfg: VadConfig | None = None) -> None:
        self.cfg = cfg or VadConfig()
        self._vad = webrtcvad.Vad(self.cfg.aggressiveness)
        self._tail = b""  # leftover bytes < one frame
        self._voiced_ms = 0
        self._silence_ms = 0
        self._in_utterance = False

    # ------------------------------------------------------------------ feed
    def feed(self, pcm_bytes: bytes) -> Iterable[VadEvent]:
        """Process ``pcm_bytes`` and yield events.

        ``pcm_bytes`` must be PCM16 mono LE at the configured sample rate.
        Partial frames are buffered between calls.
        """
        events: list[VadEvent] = []
        data = self._tail + pcm_bytes
        fb = self.cfg.frame_bytes
        i = 0
        while i + fb <= len(data):
            frame = data[i : i + fb]
            i += fb
            is_speech = self._vad.is_speech(frame, self.cfg.sample_rate)
            if is_speech:
                self._voiced_ms += self.cfg.frame_ms
                self._silence_ms = 0
                if not self._in_utterance and self._voiced_ms >= self.cfg.min_voiced_ms:
                    self._in_utterance = True
                    events.append(VadEvent.VOICED_START)
            else:
                if self._in_utterance:
                    self._silence_ms += self.cfg.frame_ms
                    if self._silence_ms >= self.cfg.silence_ms:
                        events.append(VadEvent.UTTERANCE_END)
                        self._reset_after_utterance()
                else:
                    # decay voiced counter when silence follows a tiny burst
                    self._voiced_ms = max(0, self._voiced_ms - self.cfg.frame_ms)
        self._tail = data[i:]
        return events

    def _reset_after_utterance(self) -> None:
        self._in_utterance = False
        self._voiced_ms = 0
        self._silence_ms = 0

    def reset(self) -> None:
        self._tail = b""
        self._reset_after_utterance()

    @property
    def in_utterance(self) -> bool:
        return self._in_utterance


__all__ = ["VadConfig", "VadDetector", "VadEvent"]
