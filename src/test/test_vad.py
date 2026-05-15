"""Synthetic VAD tests using webrtcvad on tone vs silence."""

from __future__ import annotations

import numpy as np

from vision_asst.streaming.audio import int16_to_bytes
from vision_asst.streaming.vad import VadConfig, VadDetector, VadEvent


def _silence(ms: int, sr: int = 16000) -> bytes:
    n = int(sr * ms / 1000)
    return int16_to_bytes(np.zeros(n, dtype=np.int16))


def _tone(ms: int, sr: int = 16000, freq: int = 440, amp: int = 16000) -> bytes:
    n = int(sr * ms / 1000)
    t = np.arange(n) / sr
    sig = (amp * np.sin(2 * np.pi * freq * t)).astype(np.int16)
    return int16_to_bytes(sig)


def test_silence_emits_no_events() -> None:
    vad = VadDetector(VadConfig(aggressiveness=2))
    events = list(vad.feed(_silence(500)))
    assert events == []
    assert not vad.in_utterance


def test_tone_then_silence_yields_voiced_then_utterance_end() -> None:
    cfg = VadConfig(aggressiveness=1, min_voiced_ms=100, silence_ms=200)
    vad = VadDetector(cfg)
    events: list[VadEvent] = []
    events += list(vad.feed(_tone(400)))
    events += list(vad.feed(_silence(400)))
    assert VadEvent.VOICED_START in events
    assert VadEvent.UTTERANCE_END in events
    # voiced_start must come before utterance_end
    assert events.index(VadEvent.VOICED_START) < events.index(VadEvent.UTTERANCE_END)


def test_brief_blip_does_not_trigger_voiced_start() -> None:
    cfg = VadConfig(aggressiveness=2, min_voiced_ms=400, silence_ms=200)
    vad = VadDetector(cfg)
    events = list(vad.feed(_tone(40)))  # very short
    events += list(vad.feed(_silence(300)))
    assert VadEvent.VOICED_START not in events


def test_partial_frame_buffered_between_calls() -> None:
    cfg = VadConfig(aggressiveness=1, min_voiced_ms=80, silence_ms=200)
    vad = VadDetector(cfg)
    pcm = _tone(200)
    # Split into 5-byte chunks (intentionally awkward) — VAD should still
    # consume full frames once enough bytes accumulate.
    out: list[VadEvent] = []
    for i in range(0, len(pcm), 5):
        out += list(vad.feed(pcm[i : i + 5]))
    out += list(vad.feed(_silence(400)))
    assert VadEvent.VOICED_START in out
    assert VadEvent.UTTERANCE_END in out
