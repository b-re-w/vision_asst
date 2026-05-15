"""Wrapper around vllm-omni's ``AsyncOmni`` orchestrator.

vllm-omni 0.20 exposes a multi-stage omni-modal engine via ``vllm_omni.AsyncOmni``
(NOT vanilla ``vllm.AsyncLLMEngine`` — that one cannot produce audio output).
This module wraps ``AsyncOmni`` behind a small mock-friendly Protocol so the
WebSocket session orchestrator can stay GPU-free in tests.

The audio extraction mirrors the helpers in
``vllm_omni.entrypoints.openai.serving_video_stream`` so the on-the-wire
behaviour matches the reference HTTP server. Heavy imports (``vllm_omni``,
``torch``, ``PIL``) are deferred to :meth:`start`.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

from ..config import Settings
from .prompt import build_chat_messages

if TYPE_CHECKING:  # pragma: no cover
    pass

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public chunk type
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OmniChunk:
    """Streaming output chunk from the engine."""

    text: str = ""
    audio_pcm16: np.ndarray | None = None
    finished: bool = False


# ---------------------------------------------------------------------------
# Protocol so tests can swap in a fake. NOTE: ``generate`` is not ``async``
# because the concrete implementation is an async generator (``async def`` +
# ``yield``); calling it returns an ``AsyncIterator`` directly without an
# enclosing ``await``.
# ---------------------------------------------------------------------------


class OmniEngineProto(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def is_ready(self) -> bool: ...
    @property
    def model_name(self) -> str: ...
    def generate(
        self,
        *,
        audio_pcm16: bytes,
        audio_sr: int,
        jpeg_frames: list[bytes],
        system_prompt: str,
        request_id: str | None = None,
    ) -> AsyncIterator[OmniChunk]: ...
    async def abort(self, request_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Defaults / constants matching vllm-omni reference implementation
# ---------------------------------------------------------------------------

# Output modalities requested from the model. ``"text"`` gives streaming
# captions; ``"audio"`` triggers the speech-synthesis stage.
DEFAULT_OUTPUT_MODALITIES: tuple[str, ...] = ("text", "audio")
# Codec frame size used to strip the leading CausalConv artifact on the first
# audio chunk (mirrors ``_CODEC_FRAME_SAMPLES`` in serving_video_stream.py).
_CODEC_FRAME_SAMPLES = 480


# ---------------------------------------------------------------------------
# vllm-omni implementation
# ---------------------------------------------------------------------------


@dataclass
class VllmOmniEngine:
    """Concrete OmniEngine backed by vllm-omni's ``AsyncOmni`` orchestrator."""

    settings: Settings
    _engine: Any = field(default=None, repr=False)
    _ready: bool = False
    _missing_audio_logged: bool = False
    _start_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def model_name(self) -> str:
        return self.settings.model

    def is_ready(self) -> bool:
        return self._ready

    # ----------------------------------------------------------------- start
    async def start(self) -> None:
        async with self._start_lock:
            if self._ready:
                return
            log.info(
                "Loading vllm-omni AsyncOmni model=%s tp=%s mem=%.2f",
                self.settings.model,
                self.settings.tp_size,
                self.settings.gpu_memory_utilization,
            )
            kwargs = self._async_omni_kwargs()
            # Lazy import — pulls in CUDA / vllm only here.
            import vllm_omni  # noqa: F401  (registers configs/parsers as side effect)
            from vllm_omni import AsyncOmni  # type: ignore[attr-defined]

            self._engine = await asyncio.to_thread(AsyncOmni, model=self.settings.model, **kwargs)
            self._ready = True
            log.info("vllm-omni AsyncOmni ready")

    def _async_omni_kwargs(self) -> dict[str, Any]:
        """Build kwargs for ``AsyncOmni`` from project settings.

        We hand AsyncOmni the upstream-bundled ``qwen3_omni_moe.yaml`` deploy
        config so each stage gets its own ``gpu_memory_utilization``,
        ``enforce_eager`` etc. (Stage 0 thinker on GPU 0 standalone, Stages
        1+2 talker/code2wav share GPU 1 with utilizations 0.5 + 0.3.) A single
        global ``gpu_memory_utilization`` does not work because Stages 1 and 2
        share a GPU and would each request the same fraction of total memory.
        """
        import os

        import vllm_omni  # already imported in start()
        deploy_yaml = os.path.join(
            os.path.dirname(vllm_omni.__file__), "deploy", "qwen3_omni_moe.yaml"
        )
        return {
            "stage_configs_path": deploy_yaml,
            "trust_remote_code": True,
            "stage_init_timeout": 7200,
            "init_timeout": 7200,
        }

    # ------------------------------------------------------------------ stop
    async def stop(self) -> None:
        if self._engine is None:
            return
        try:
            await asyncio.to_thread(self._engine.shutdown)
        finally:
            self._engine = None
            self._ready = False

    # -------------------------------------------------------------- generate
    async def generate(
        self,
        *,
        audio_pcm16: bytes,
        audio_sr: int,
        jpeg_frames: list[bytes],
        system_prompt: str,
        request_id: str | None = None,
    ) -> AsyncIterator[OmniChunk]:
        if not self._ready or self._engine is None:
            raise RuntimeError("engine not started")

        rid = request_id or f"va-{uuid.uuid4().hex[:12]}"
        engine_prompt = await self._build_engine_prompt(
            audio_pcm16=audio_pcm16,
            audio_sr=audio_sr,
            jpeg_frames=jpeg_frames,
            system_prompt=system_prompt,
        )

        previous_text = ""
        chunks_drained = 0
        is_first_audio = True

        async for output in self._engine.generate(
            prompt=engine_prompt,
            request_id=rid,
            output_modalities=list(DEFAULT_OUTPUT_MODALITIES),
        ):
            out_type = getattr(output, "final_output_type", "text")
            if out_type == "audio":
                pcm16, chunks_drained = self._extract_audio_pcm16(
                    output, chunks_drained, is_first=is_first_audio
                )
                if pcm16 is not None and pcm16.size > 0:
                    is_first_audio = False
                    yield OmniChunk(audio_pcm16=pcm16)
            else:
                delta, previous_text = _extract_text_delta(output, previous_text)
                if delta:
                    yield OmniChunk(text=delta)

        yield OmniChunk(finished=True)

    # ----------------------------------------------------- engine-prompt path
    async def _build_engine_prompt(
        self,
        *,
        audio_pcm16: bytes,
        audio_sr: int,
        jpeg_frames: list[bytes],
        system_prompt: str,
    ) -> Any:
        """Convert raw bytes into a vllm-omni engine prompt with multimodal data.

        Decodes JPEGs to PIL images and PCM16 bytes to a float32 numpy
        array, then renders the chat template via the engine's tokenizer
        and packages them as a vllm ``TokensPrompt`` with ``multi_modal_data``.
        """
        from PIL import Image  # type: ignore[import-not-found]
        from vllm import TokensPrompt  # type: ignore[import-not-found]

        messages = build_chat_messages(system_prompt=system_prompt, has_audio=True, has_video=bool(jpeg_frames))

        tokenizer = await self._get_tokenizer()
        prompt_text: str = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )
        prompt_token_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]

        images = [Image.open(io.BytesIO(b)).convert("RGB") for b in jpeg_frames]
        audio_np = np.frombuffer(audio_pcm16, dtype="<i2").astype(np.float32) / 32768.0

        mm_data: dict[str, Any] = {"audio": [(audio_np, audio_sr)]}
        if images:
            mm_data["image"] = images

        return TokensPrompt(prompt_token_ids=prompt_token_ids, multi_modal_data=mm_data)

    async def _get_tokenizer(self) -> Any:
        return await self._engine.get_tokenizer()

    # ------------------------------------------------- audio extraction path
    def _extract_audio_pcm16(
        self, output: Any, chunks_drained: int, *, is_first: bool
    ) -> tuple[np.ndarray | None, int]:
        """Return (PCM16 numpy array, updated chunks_drained).

        Mirrors ``serving_video_stream._extract_audio_delta_b64`` but yields
        int16 PCM directly instead of a base64-WAV envelope.
        """
        audio_data = _get_audio_data(output)
        if audio_data is None:
            if not self._missing_audio_logged:
                log.debug(
                    "no multimodal_output['audio'] on completion; final_output_type=%r",
                    getattr(output, "final_output_type", None),
                )
                self._missing_audio_logged = True
            return None, chunks_drained

        import torch  # type: ignore[import-not-found]

        if not isinstance(audio_data, list):
            if chunks_drained >= 1:
                return None, chunks_drained
            tail_np = _tensor_to_1d_np(audio_data)
            new_drained = 1
        else:
            n = len(audio_data)
            if n <= chunks_drained:
                return None, chunks_drained
            new_chunks = audio_data[chunks_drained:]
            tail = new_chunks[0] if len(new_chunks) == 1 else torch.cat(new_chunks, dim=-1)
            tail_np = _tensor_to_1d_np(tail)
            new_drained = n

        if tail_np is None or tail_np.size == 0:
            return None, new_drained
        if is_first and tail_np.size > _CODEC_FRAME_SAMPLES * 2:
            tail_np = tail_np[_CODEC_FRAME_SAMPLES:]
        # float32 in [-1,1] → int16 PCM
        clipped = np.clip(tail_np, -1.0, 1.0)
        pcm16 = (clipped * 32767.0).astype(np.int16)
        return pcm16, new_drained

    # --------------------------------------------------------------- abort
    async def abort(self, request_id: str) -> None:
        if self._engine is None:
            return
        await self._engine.abort(request_id)


# ---------------------------------------------------------------------------
# Free helpers — mirrors of vllm-omni's serving_video_stream implementation
# ---------------------------------------------------------------------------


def _get_audio_data(result: Any) -> Any:
    """Walk OmniRequestOutput → outputs[0].multimodal_output['audio']."""
    request_output = getattr(result, "request_output", None)
    if request_output is None:
        return None
    outputs = getattr(request_output, "outputs", None)
    if not isinstance(outputs, list) or not outputs:
        return None
    mm_output = getattr(outputs[0], "multimodal_output", None)
    if not isinstance(mm_output, dict):
        return None
    return mm_output.get("audio")


def _extract_text_delta(result: Any, previous_text: str) -> tuple[str, str]:
    if getattr(result, "final_output_type", "text") != "text":
        return "", previous_text
    request_output = getattr(result, "request_output", None)
    if request_output is None:
        return "", previous_text
    outputs = getattr(request_output, "outputs", None)
    if not isinstance(outputs, list) or not outputs:
        return "", previous_text
    text = getattr(outputs[0], "text", None)
    if not isinstance(text, str) or not text:
        return "", previous_text
    if text.startswith(previous_text):
        return text[len(previous_text) :], text
    return text, text


def _tensor_to_1d_np(t: Any) -> np.ndarray | None:
    if t is None or not hasattr(t, "float"):
        return None
    arr = t.float().detach().cpu().numpy()
    if arr.ndim > 1:
        arr = arr.flatten()
    return arr


__all__ = ["DEFAULT_OUTPUT_MODALITIES", "OmniChunk", "OmniEngineProto", "VllmOmniEngine"]
