"""Per-WebSocket session orchestrator.

Coordinates VAD, frame buffering, engine generation, and barge-in. Exposes
a single :meth:`WsSession.run` coroutine driven by the WS endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Literal, Protocol

import numpy as np
from pydantic import ValidationError

from ..config import Settings
from ..engine.omni_engine import OmniChunk, OmniEngineProto
from .audio import AudioRingBuffer, int16_to_bytes
from .protocol import (
    MAX_JPEG_BYTES,
    MAX_PCM_BYTES,
    MAX_TEXT_FRAME_BYTES,
    AudioEndMsg,
    AudioStartMsg,
    ByeMsg,
    CancelMsg,
    EndOfTurnMsg,
    ErrorMsg,
    HelloMsg,
    ReadyMsg,
    SystemOverrideMsg,
    TextDeltaMsg,
    TurnEndMsg,
    TurnStartMsg,
    is_audio_in,
    is_video_in,
    pack_audio_out,
    parse_inbound,
    unpack_binary,
    validate_jpeg,
)
from .vad import VadConfig, VadDetector, VadEvent
from .video import FrameBuffer

log = logging.getLogger(__name__)

TurnReason = Literal["complete", "cancelled", "interrupted", "error"]


# ---------------------------------------------------------------------------
# Transport abstraction (WebSocket-shaped)
# ---------------------------------------------------------------------------


class WsTransport(Protocol):
    """Minimal interface a WebSocket-like object must satisfy.

    Tests pass a fake transport so the session logic runs without a real
    Starlette WS.
    """

    async def receive(self) -> dict: ...  # {"type": "websocket.receive", "text"|"bytes": ...}
    async def send_text(self, data: str) -> None: ...
    async def send_bytes(self, data: bytes) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


# ---------------------------------------------------------------------------
# Session state machine
# ---------------------------------------------------------------------------


@dataclass
class _Turn:
    turn_id: str
    audio: np.ndarray
    frames: list[bytes]
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    request_id: str = field(default_factory=lambda: f"va-{uuid.uuid4().hex[:12]}")


class WsSession:
    """Drives a single client connection from hello to bye."""

    def __init__(
        self,
        ws: WsTransport,
        engine: OmniEngineProto,
        settings: Settings,
    ) -> None:
        self.ws = ws
        self.engine = engine
        self.settings = settings
        self.audio_buffer = AudioRingBuffer(
            sample_rate=settings.input_sr, max_ms=30_000
        )
        self.frames = FrameBuffer(window_ms=settings.frame_window_ms)
        self.vad = VadDetector(
            VadConfig(
                sample_rate=settings.input_sr,
                frame_ms=settings.vad_frame_ms,
                aggressiveness=settings.vad_aggressiveness,
                min_voiced_ms=settings.min_voiced_ms,
                silence_ms=settings.silence_ms,
            )
        )
        self.system_prompt = settings.system_prompt
        self.turn_queue: asyncio.Queue[_Turn] = asyncio.Queue(maxsize=1)
        self.active_turn: _Turn | None = None
        self._closing = asyncio.Event()

    # =================================================================== run
    async def run(self) -> None:
        await self._send_json(
            ReadyMsg(
                model=self.engine.model_name,
                sample_rate_in=self.settings.input_sr,
                sample_rate_out=self.settings.output_sr,
            )
        )
        reader = asyncio.create_task(self._reader_loop(), name="va-reader")
        worker = asyncio.create_task(self._worker_loop(), name="va-worker")
        try:
            await self._closing.wait()
        finally:
            for t in (reader, worker):
                t.cancel()
            await asyncio.gather(reader, worker, return_exceptions=True)

    async def _stop(self) -> None:
        if not self._closing.is_set():
            self._closing.set()

    # =============================================================== reader
    async def _reader_loop(self) -> None:
        idle_timeout = self.settings.idle_timeout_s
        try:
            while not self._closing.is_set():
                try:
                    msg = await asyncio.wait_for(self.ws.receive(), timeout=idle_timeout)
                except TimeoutError:
                    await self._safe_send_error("idle_timeout", "no traffic — closing session")
                    break
                kind = msg.get("type")
                if kind == "websocket.disconnect":
                    break
                if "bytes" in msg and msg["bytes"] is not None:
                    await self._on_binary(msg["bytes"])
                elif "text" in msg and msg["text"] is not None:
                    await self._on_text(msg["text"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("reader loop crashed: %s", exc)
            await self._safe_send_error("reader_error", str(exc))
        finally:
            await self._stop()

    async def _on_binary(self, data: bytes) -> None:
        try:
            tag, payload = unpack_binary(data)
        except ValueError:
            return
        if is_audio_in(tag):
            if len(payload) > MAX_PCM_BYTES:
                await self._safe_send_error("frame_too_large", "audio frame > 1s")
                await self._stop()
                return
            await self._on_audio_in(payload)
        elif is_video_in(tag):
            if len(payload) > MAX_JPEG_BYTES or not validate_jpeg(payload):
                await self._safe_send_error("bad_jpeg", "invalid or oversized JPEG frame")
                return
            self.frames.add(payload)
        else:
            log.debug("ignoring unknown binary tag 0x%02x (%d bytes)", tag, len(payload))

    async def _on_audio_in(self, pcm_bytes: bytes) -> None:
        # Always feed the buffer first so the active-turn snapshot includes
        # samples that arrived right before utterance_end.
        self.audio_buffer.append_bytes(pcm_bytes)
        events = list(self.vad.feed(pcm_bytes))
        for ev in events:
            if ev is VadEvent.VOICED_START:
                await self._on_voiced_start()
            elif ev is VadEvent.UTTERANCE_END:
                await self._on_utterance_end()

    async def _on_voiced_start(self) -> None:
        # Barge-in: cancel an in-flight generation when the user starts
        # speaking again.
        if self.active_turn is not None and not self.active_turn.cancel_event.is_set():
            log.info("barge-in: cancelling turn %s", self.active_turn.turn_id)
            self.active_turn.cancel_event.set()
            await self.engine.abort(self.active_turn.request_id)

    async def _on_utterance_end(self) -> None:
        audio = self.audio_buffer.take_all()
        # Reset VAD state so silence_ms / voiced_ms counters do not bleed
        # from the previous turn into the next one.
        self.vad.reset()
        if audio.size == 0:
            return
        frames = self.frames.recent(self.settings.max_frames_per_turn)
        turn = _Turn(turn_id=f"t-{uuid.uuid4().hex[:8]}", audio=audio, frames=frames)
        # Drop-newest backpressure: if the worker is still draining a
        # previous turn, evict the queued one before enqueueing the new
        # turn so the reader never blocks.
        try:
            self.turn_queue.put_nowait(turn)
        except asyncio.QueueFull:
            try:
                dropped = self.turn_queue.get_nowait()
                log.info("dropping queued turn %s for newer %s", dropped.turn_id, turn.turn_id)
            except asyncio.QueueEmpty:
                pass
            self.turn_queue.put_nowait(turn)

    async def _on_text(self, text: str) -> None:
        if len(text) > MAX_TEXT_FRAME_BYTES:
            await self._safe_send_error("text_too_large", "control message too large")
            return
        try:
            msg = parse_inbound(text)
        except ValidationError as exc:
            errors = exc.errors()
            if errors:
                first = errors[0]
                detail = f"{'.'.join(str(p) for p in first.get('loc', ()))}: {first.get('msg')}"
            else:
                detail = "validation failed"
            await self._safe_send_error("bad_message", detail)
            return
        if isinstance(msg, HelloMsg):
            log.info("hello session_id=%s fps=%s", msg.session_id, msg.video_fps)
        elif isinstance(msg, EndOfTurnMsg):
            await self._on_utterance_end()
        elif isinstance(msg, CancelMsg):
            if self.active_turn is not None:
                self.active_turn.cancel_event.set()
                await self.engine.abort(self.active_turn.request_id)
        elif isinstance(msg, SystemOverrideMsg):
            self.system_prompt = msg.prompt
        elif isinstance(msg, ByeMsg):
            await self._stop()

    # =============================================================== worker
    async def _worker_loop(self) -> None:
        try:
            while not self._closing.is_set():
                turn = await self.turn_queue.get()
                await self._run_turn(turn)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("worker loop crashed: %s", exc)
            await self._safe_send_error("worker_error", str(exc))
        finally:
            await self._stop()

    async def _run_turn(self, turn: _Turn) -> None:
        self.active_turn = turn
        await self._send_json(TurnStartMsg(turn_id=turn.turn_id))
        await self._send_json(
            AudioStartMsg(turn_id=turn.turn_id, sample_rate=self.settings.output_sr)
        )
        reason: TurnReason = "complete"
        agen = None
        try:
            audio_bytes = int16_to_bytes(turn.audio)
            agen = self.engine.generate(
                audio_pcm16=audio_bytes,
                audio_sr=self.settings.input_sr,
                jpeg_frames=turn.frames,
                system_prompt=self.system_prompt,
                request_id=turn.request_id,
            )
            async for chunk in agen:
                if turn.cancel_event.is_set():
                    reason = "interrupted"
                    break
                await self._handle_chunk(turn, chunk)
                if chunk.finished:
                    break
        except asyncio.CancelledError:
            reason = "cancelled"
            raise
        except Exception as exc:
            log.exception("turn %s failed: %s", turn.turn_id, exc)
            reason = "error"
            await self._safe_send_error("generation_error", str(exc))
        finally:
            # Closing the async generator releases the engine request even
            # when the loop broke early (cancel/interrupt).
            if agen is not None and hasattr(agen, "aclose"):
                try:
                    await agen.aclose()
                except Exception as close_exc:
                    log.debug("agen.aclose failed: %s", close_exc)
            await self._send_json(AudioEndMsg(turn_id=turn.turn_id))
            await self._send_json(TurnEndMsg(turn_id=turn.turn_id, reason=reason))
            self.active_turn = None

    async def _handle_chunk(self, turn: _Turn, chunk: OmniChunk) -> None:
        if chunk.text:
            await self._send_json(TextDeltaMsg(turn_id=turn.turn_id, text=chunk.text))
        if chunk.audio_pcm16 is not None and chunk.audio_pcm16.size > 0:
            await self.ws.send_bytes(pack_audio_out(chunk.audio_pcm16))

    # ============================================================== helpers
    async def _send_json(self, model) -> None:
        try:
            await self.ws.send_text(model.to_json())
        except Exception as exc:  # pragma: no cover — connection gone
            log.debug("send_text failed: %s", exc)
            await self._stop()

    async def _safe_send_error(self, code: str, message: str) -> None:
        try:
            await self.ws.send_text(ErrorMsg(code=code, message=message).to_json())
        except Exception as exc:
            log.debug("send_text(error) failed: %s", exc)


__all__ = ["TurnReason", "WsSession", "WsTransport"]
