"""Runtime configuration loaded from environment variables.

All settings are prefixed with ``VA_``. See ``configs/default.env`` for an
example. Defaults match the values used by ``run.sh``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = (
    "당신은 시각 장애인을 돕는 AI 비전 어시스턴트입니다. "
    "사용자가 보낸 카메라 영상과 음성 질문을 분석해 주변 상황과 사물의 위치, "
    "글자, 위험 요소를 한국어로 짧고 명확하게 설명하세요. "
    "가능하면 한 문장으로 답하고, 위험이 감지되면 가장 먼저 알리세요."
)


class Settings(BaseSettings):
    """Process-wide configuration."""

    model_config = SettingsConfigDict(env_prefix="VA_", env_file=".env", extra="ignore")

    # Engine
    model: str = "marksverdhei/Qwen3-Omni-30B-A3B-FP8"
    tp_size: int = 1
    gpu_memory_utilization: float = 0.85
    max_model_len: int = 32768
    enforce_eager: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    ws_max_size: int = 1 * 1024 * 1024  # 1 MiB per WS frame; protocol caps are tighter
    ws_ping_interval: float = 20.0
    ws_ping_timeout: float = 20.0
    # DoS guards
    max_concurrent_ws: int = 8
    max_concurrent_turns: int = 2
    idle_timeout_s: float = 300.0  # close a session that sends nothing for this long

    # Audio
    input_sr: int = 16000
    output_sr: int = 24000

    # VAD / turn detection (milliseconds)
    vad_aggressiveness: int = Field(default=2, ge=0, le=3)
    vad_frame_ms: int = 20
    silence_ms: int = 300
    min_voiced_ms: int = 250
    barge_in_ms: int = 150

    # Video framing
    video_fps_max: int = 4
    max_frames_per_turn: int = 4
    frame_window_ms: int = 4000

    # Generation
    max_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9

    # Prompting
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    @property
    def vad_frame_samples(self) -> int:
        return int(self.input_sr * self.vad_frame_ms / 1000)

    @property
    def vad_frame_bytes(self) -> int:
        return self.vad_frame_samples * 2  # int16


def get_settings() -> Settings:
    """Construct a fresh ``Settings`` instance (no global cache)."""
    return Settings()
