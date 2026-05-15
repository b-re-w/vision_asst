"""End-to-end session tests using a fake transport and fake engine."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import numpy as np
import pytest

from vision_asst.streaming.audio import int16_to_bytes
from vision_asst.streaming.protocol import (
    TAG_AUDIO_IN,
    TAG_AUDIO_OUT,
    TAG_VIDEO_IN,
)
from vision_asst.streaming.session import WsSession


class FakeTransport:
    def __init__(self) -> None:
        self.in_q: asyncio.Queue[dict] = asyncio.Queue()
        self.sent_text: list[str] = []
        self.sent_bytes: list[bytes] = []
        self.closed = False

    async def receive(self) -> dict:
        return await self.in_q.get()

    async def send_text(self, data: str) -> None:
        self.sent_text.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = True

    # convenience helpers for tests
    async def push_audio_bytes(self, pcm: bytes) -> None:
        await self.in_q.put({"type": "websocket.receive", "bytes": bytes([TAG_AUDIO_IN]) + pcm})

    async def push_jpeg(self, jpg: bytes) -> None:
        await self.in_q.put({"type": "websocket.receive", "bytes": bytes([TAG_VIDEO_IN]) + jpg})

    async def push_json(self, obj: dict[str, Any]) -> None:
        await self.in_q.put({"type": "websocket.receive", "text": json.dumps(obj)})

    async def disconnect(self) -> None:
        await self.in_q.put({"type": "websocket.disconnect"})


def _tone(ms: int, sr: int = 16000) -> bytes:
    n = int(sr * ms / 1000)
    t = np.arange(n) / sr
    sig = (16000 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
    return int16_to_bytes(sig)


def _silence(ms: int, sr: int = 16000) -> bytes:
    n = int(sr * ms / 1000)
    return int16_to_bytes(np.zeros(n, dtype=np.int16))


# Minimal valid-shape JPEG bytes (SOI + dummy + EOI) — passes our
# header-only validator without being a real image. Real frames are decoded
# only by the engine's PIL path which is mocked out in unit tests.
_VALID_JPEG = b"\xff\xd8" + b"\x00" * 32 + b"\xff\xd9"


async def _run_with_timeout(coro, timeout: float = 5.0) -> None:
    await asyncio.wait_for(coro, timeout=timeout)


@pytest.mark.asyncio
async def test_full_turn_lifecycle(settings, fake_engine) -> None:
    await fake_engine.start()
    transport = FakeTransport()
    session = WsSession(ws=transport, engine=fake_engine, settings=settings)

    runner = asyncio.create_task(session.run())

    # Push some audio + a frame, then issue an explicit end_of_turn to drive
    # the worker. (VAD-driven detection is exercised separately in test_vad.py
    # — webrtcvad does not classify pure synthetic tones reliably enough at
    # the production aggressiveness setting.)
    await transport.push_jpeg(_VALID_JPEG)
    for _ in range(20):
        await transport.push_audio_bytes(_tone(20))
    await transport.push_json({"type": "end_of_turn"})

    # Wait for the model output to be written
    deadline = asyncio.get_event_loop().time() + 4.0
    while asyncio.get_event_loop().time() < deadline:
        types = [json.loads(t).get("type") for t in transport.sent_text]
        if "turn.end" in types:
            break
        await asyncio.sleep(0.05)

    await transport.push_json({"type": "bye"})
    await _run_with_timeout(runner, timeout=2.0)

    types = [json.loads(t).get("type") for t in transport.sent_text]
    assert "ready" in types
    assert "turn.start" in types
    assert "audio.start" in types
    assert "text.delta" in types
    assert "audio.end" in types
    assert any(json.loads(t).get("type") == "turn.end" for t in transport.sent_text)
    # at least one audio binary frame produced and tagged correctly
    assert any(b and b[0] == TAG_AUDIO_OUT for b in transport.sent_bytes)
    assert fake_engine.calls, "engine.generate should have been called"


@pytest.mark.asyncio
async def test_explicit_end_of_turn_drives_generation(settings, fake_engine) -> None:
    await fake_engine.start()
    transport = FakeTransport()
    session = WsSession(ws=transport, engine=fake_engine, settings=settings)
    runner = asyncio.create_task(session.run())

    # Push some audio without enough silence to trigger VAD,
    # then send an explicit end_of_turn.
    for _ in range(10):
        await transport.push_audio_bytes(_tone(20))
    await transport.push_json({"type": "end_of_turn"})

    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline:
        types = [json.loads(t).get("type") for t in transport.sent_text]
        if "turn.end" in types:
            break
        await asyncio.sleep(0.05)

    await transport.push_json({"type": "bye"})
    await _run_with_timeout(runner, timeout=2.0)

    assert fake_engine.calls, "engine.generate should have been called via explicit end_of_turn"


@pytest.mark.asyncio
async def test_cancel_message_aborts_active_turn(settings, fake_engine) -> None:
    # Slow the engine so the cancel arrives mid-stream.
    fake_engine.n_chunks = 20
    fake_engine.delay_per_chunk = 0.1
    await fake_engine.start()
    transport = FakeTransport()
    session = WsSession(ws=transport, engine=fake_engine, settings=settings)
    runner = asyncio.create_task(session.run())

    for _ in range(10):
        await transport.push_audio_bytes(_tone(20))
    await transport.push_json({"type": "end_of_turn"})

    # Wait until generation is in flight
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        if session.active_turn is not None:
            break
        await asyncio.sleep(0.02)

    await transport.push_json({"type": "cancel"})
    deadline = asyncio.get_event_loop().time() + 3.0
    while asyncio.get_event_loop().time() < deadline:
        if any(json.loads(t).get("type") == "turn.end" for t in transport.sent_text):
            break
        await asyncio.sleep(0.05)

    await transport.push_json({"type": "bye"})
    await _run_with_timeout(runner, timeout=2.0)

    assert fake_engine.aborted, "engine.abort should have been invoked"


@pytest.mark.asyncio
async def test_oversized_audio_frame_closes_session(settings, fake_engine) -> None:
    await fake_engine.start()
    transport = FakeTransport()
    session = WsSession(ws=transport, engine=fake_engine, settings=settings)
    runner = asyncio.create_task(session.run())

    # 64 KiB of zero PCM > MAX_PCM_BYTES (32_000)
    await transport.push_audio_bytes(b"\x00" * 64_000)
    await _run_with_timeout(runner, timeout=2.0)

    types = [json.loads(t).get("type") for t in transport.sent_text]
    assert "error" in types
    err = next(json.loads(t) for t in transport.sent_text if json.loads(t).get("type") == "error")
    assert err["code"] == "frame_too_large"


@pytest.mark.asyncio
async def test_oversized_text_frame_rejected(settings, fake_engine) -> None:
    await fake_engine.start()
    transport = FakeTransport()
    session = WsSession(ws=transport, engine=fake_engine, settings=settings)
    runner = asyncio.create_task(session.run())

    huge = "{" + "x" * (32 * 1024) + "}"
    await transport.in_q.put({"type": "websocket.receive", "text": huge})
    await transport.push_json({"type": "bye"})
    await _run_with_timeout(runner, timeout=2.0)

    types = [json.loads(t).get("type") for t in transport.sent_text]
    assert "error" in types
    err = next(json.loads(t) for t in transport.sent_text if json.loads(t).get("type") == "error")
    assert err["code"] == "text_too_large"


@pytest.mark.asyncio
async def test_invalid_jpeg_rejected_but_session_continues(settings, fake_engine) -> None:
    await fake_engine.start()
    transport = FakeTransport()
    session = WsSession(ws=transport, engine=fake_engine, settings=settings)
    runner = asyncio.create_task(session.run())

    await transport.push_jpeg(b"not really a jpeg")  # missing SOI/EOI
    await transport.push_json({"type": "bye"})
    await _run_with_timeout(runner, timeout=2.0)

    types = [json.loads(t).get("type") for t in transport.sent_text]
    assert "error" in types
    codes = [json.loads(t).get("code") for t in transport.sent_text if json.loads(t).get("type") == "error"]
    assert "bad_jpeg" in codes


@pytest.mark.asyncio
async def test_extra_field_in_inbound_msg_rejected(settings, fake_engine) -> None:
    await fake_engine.start()
    transport = FakeTransport()
    session = WsSession(ws=transport, engine=fake_engine, settings=settings)
    runner = asyncio.create_task(session.run())

    await transport.push_json({"type": "hello", "session_id": "s1", "video_fps": 2, "extra": "no"})
    await transport.push_json({"type": "bye"})
    await _run_with_timeout(runner, timeout=2.0)

    types = [json.loads(t).get("type") for t in transport.sent_text]
    assert "error" in types
    codes = [json.loads(t).get("code") for t in transport.sent_text if json.loads(t).get("type") == "error"]
    assert "bad_message" in codes


@pytest.mark.asyncio
async def test_bad_json_returns_error_but_keeps_socket_alive(settings, fake_engine) -> None:
    await fake_engine.start()
    transport = FakeTransport()
    session = WsSession(ws=transport, engine=fake_engine, settings=settings)
    runner = asyncio.create_task(session.run())

    await transport.in_q.put({"type": "websocket.receive", "text": "{not json"})
    # Then a clean bye
    await transport.push_json({"type": "bye"})
    await _run_with_timeout(runner, timeout=2.0)

    types = [json.loads(t).get("type") for t in transport.sent_text]
    assert "error" in types
