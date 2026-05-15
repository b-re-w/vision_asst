"""WebSocket framing helpers and JSON control-message schemas.

Binary frames carry a single tag byte (0x01/0x02 inbound, 0x81 outbound)
followed by raw payload bytes. Text frames carry JSON objects with a
``type`` field. All inbound JSON messages are parsed via Pydantic
discriminated unions with ``extra="forbid"`` so unknown fields are rejected.
"""

from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

# ---------------------------------------------------------------------------
# Binary tags
# ---------------------------------------------------------------------------

TAG_AUDIO_IN = 0x01  # client → server, PCM16 mono LE
TAG_VIDEO_IN = 0x02  # client → server, JPEG bytes
TAG_AUDIO_OUT = 0x81  # server → client, PCM16 mono LE

# Per-frame size caps. The session orchestrator drops frames that exceed
# these and the connection is closed for oversized audio (which signals a
# misbehaving client). See ``streaming/session.py`` for enforcement.
MAX_PCM_BYTES = 32_000  # 1 s of 16 kHz int16 mono
MAX_JPEG_BYTES = 512 * 1024  # 512 KiB
MAX_TEXT_FRAME_BYTES = 16 * 1024  # 16 KiB


def pack_audio_out(pcm: np.ndarray) -> bytes:
    """Pack an int16 PCM array as a tagged binary frame."""
    if pcm.dtype != np.int16:
        raise TypeError(f"expected int16 PCM, got {pcm.dtype}")
    return bytes([TAG_AUDIO_OUT]) + pcm.tobytes()


def unpack_binary(data: bytes) -> tuple[int, bytes]:
    """Split a binary frame into ``(tag, payload)``."""
    if not data:
        raise ValueError("empty binary frame")
    return data[0], data[1:]


def is_audio_in(tag: int) -> bool:
    return tag == TAG_AUDIO_IN


def is_video_in(tag: int) -> bool:
    return tag == TAG_VIDEO_IN


def validate_jpeg(payload: bytes) -> bool:
    """Cheap JPEG sanity check — SOI/EOI markers without decoding."""
    return len(payload) >= 4 and payload[:2] == b"\xff\xd8" and payload[-2:] == b"\xff\xd9"


# ---------------------------------------------------------------------------
# Inbound (client → server) JSON messages
# ---------------------------------------------------------------------------


class _InBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HelloMsg(_InBase):
    type: Literal["hello"]
    session_id: str | None = Field(default=None, max_length=128)
    sample_rate: int = 16000
    video_fps: int = Field(default=2, ge=1, le=30)

    @field_validator("sample_rate")
    @classmethod
    def _check_sr(cls, v: int) -> int:
        if v != 16000:
            raise ValueError("only sample_rate=16000 is supported")
        return v


class EndOfTurnMsg(_InBase):
    type: Literal["end_of_turn"]


class CancelMsg(_InBase):
    type: Literal["cancel"]


class SystemOverrideMsg(_InBase):
    type: Literal["system"]
    prompt: str = Field(..., min_length=1, max_length=4096)


class ByeMsg(_InBase):
    type: Literal["bye"]


InboundMsg = Annotated[
    HelloMsg | EndOfTurnMsg | CancelMsg | SystemOverrideMsg | ByeMsg,
    Field(discriminator="type"),
]

_inbound_adapter: TypeAdapter[InboundMsg] = TypeAdapter(InboundMsg)


def parse_inbound(raw: str | bytes) -> InboundMsg:
    """Parse a JSON text frame into a discriminated control message.

    Raises ``ValidationError`` on bad input.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return _inbound_adapter.validate_json(raw)


# ---------------------------------------------------------------------------
# Outbound (server → client) JSON messages
# ---------------------------------------------------------------------------


class _OutBase(BaseModel):
    def to_json(self) -> str:
        return self.model_dump_json()


class ReadyMsg(_OutBase):
    type: Literal["ready"] = "ready"
    model: str
    sample_rate_in: int
    sample_rate_out: int


class TurnStartMsg(_OutBase):
    type: Literal["turn.start"] = "turn.start"
    turn_id: str


class TurnEndMsg(_OutBase):
    type: Literal["turn.end"] = "turn.end"
    turn_id: str
    reason: Literal["complete", "cancelled", "interrupted", "error"]


class TextDeltaMsg(_OutBase):
    type: Literal["text.delta"] = "text.delta"
    turn_id: str
    text: str


class AudioStartMsg(_OutBase):
    type: Literal["audio.start"] = "audio.start"
    turn_id: str
    sample_rate: int


class AudioEndMsg(_OutBase):
    type: Literal["audio.end"] = "audio.end"
    turn_id: str


class ErrorMsg(_OutBase):
    type: Literal["error"] = "error"
    code: str
    message: str


__all__ = [
    "MAX_JPEG_BYTES",
    "MAX_PCM_BYTES",
    "MAX_TEXT_FRAME_BYTES",
    "TAG_AUDIO_IN",
    "TAG_AUDIO_OUT",
    "TAG_VIDEO_IN",
    "AudioEndMsg",
    "AudioStartMsg",
    "ByeMsg",
    "CancelMsg",
    "EndOfTurnMsg",
    "ErrorMsg",
    "HelloMsg",
    "InboundMsg",
    "ReadyMsg",
    "SystemOverrideMsg",
    "TextDeltaMsg",
    "TurnEndMsg",
    "TurnStartMsg",
    "ValidationError",
    "is_audio_in",
    "is_video_in",
    "pack_audio_out",
    "parse_inbound",
    "unpack_binary",
    "validate_jpeg",
]
