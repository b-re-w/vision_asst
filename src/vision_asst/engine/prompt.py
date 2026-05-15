"""Helpers that build chat-format messages for Qwen3-Omni.

The actual multimodal payload (PIL images + raw audio array) is attached
separately as ``multi_modal_data`` on the ``TokensPrompt`` we hand to the
engine — see :func:`vision_asst.engine.omni_engine.VllmOmniEngine._build_engine_prompt`.
The chat template only needs to know how many image / audio placeholders to
emit, which is what these messages encode.
"""

from __future__ import annotations

from typing import Any


def build_chat_messages(
    *,
    system_prompt: str,
    has_audio: bool,
    has_video: bool,
) -> list[dict[str, Any]]:
    """Assemble OpenAI-style chat messages with multimodal placeholders.

    The user message contains one ``image_url`` placeholder per image (vllm
    inserts them at template-render time using the count) plus an
    ``input_audio`` placeholder for the captured speech. When no frames are
    available, a short text instruction lets the model degrade gracefully.
    """
    user_parts: list[dict[str, Any]] = []
    if has_video:
        # Single placeholder; the engine substitutes the multi-modal data list.
        user_parts.append({"type": "image_url", "image_url": {"url": "image_placeholder"}})
    else:
        user_parts.append(
            {
                "type": "text",
                "text": "(영상 프레임 없음 — 시각 정보 없이 답할 수 있는 경우 답하고, "
                "그렇지 않으면 카메라가 가려졌을 수 있다고 알려주세요.)",
            }
        )
    if has_audio:
        user_parts.append(
            {
                "type": "input_audio",
                "input_audio": {"data": "audio_placeholder", "format": "wav"},
            }
        )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_parts},
    ]


__all__ = ["build_chat_messages"]
