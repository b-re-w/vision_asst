"""Shared test fixtures, including a fake omni engine."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import numpy as np
import pytest

from vision_asst.config import Settings
from vision_asst.engine.omni_engine import OmniChunk, OmniEngineProto


@pytest.fixture
def settings() -> Settings:
    return Settings(
        model="fake/model",
        tp_size=1,
        max_model_len=2048,
        gpu_memory_utilization=0.5,
        log_level="warning",
    )


class FakeOmniEngine(OmniEngineProto):
    """Deterministic fake engine used by session/integration tests."""

    def __init__(
        self, *, sr: int = 24000, n_chunks: int = 3, delay_per_chunk: float = 0.05
    ) -> None:
        self.sr = sr
        self.n_chunks = n_chunks
        self.delay_per_chunk = delay_per_chunk
        self._ready = False
        self.aborted: list[str] = []
        self.calls: list[dict] = []
        self._abort_events: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        self._ready = True

    async def stop(self) -> None:
        self._ready = False

    def is_ready(self) -> bool:
        return self._ready

    @property
    def model_name(self) -> str:
        return "fake/model"

    async def generate(
        self,
        *,
        audio_pcm16: bytes,
        audio_sr: int,
        jpeg_frames: list[bytes],
        system_prompt: str,
        request_id: str | None = None,
    ) -> AsyncIterator[OmniChunk]:
        rid = request_id or "fake-rid"
        self.calls.append(
            {
                "audio_len": len(audio_pcm16),
                "frames": len(jpeg_frames),
                "system_prompt": system_prompt,
                "request_id": rid,
            }
        )
        ev = self._abort_events.setdefault(rid, asyncio.Event())
        chunk_samples = self.sr // 4  # 250 ms
        for i in range(self.n_chunks):
            if ev.is_set():
                return
            await asyncio.sleep(self.delay_per_chunk)
            if ev.is_set():
                return
            text = ["안녕", "하세요", " 도와드릴게요"][i] if i < 3 else f"chunk-{i}"
            tone = np.zeros(chunk_samples, dtype=np.int16)
            yield OmniChunk(text=text, audio_pcm16=tone)
        yield OmniChunk(finished=True)

    async def abort(self, request_id: str) -> None:
        self.aborted.append(request_id)
        ev = self._abort_events.setdefault(request_id, asyncio.Event())
        ev.set()


@pytest.fixture
def fake_engine() -> FakeOmniEngine:
    return FakeOmniEngine()
