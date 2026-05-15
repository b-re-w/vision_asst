"""Protocol framing and JSON schema tests."""

from __future__ import annotations

import json

import numpy as np
import pytest
from pydantic import ValidationError

from vision_asst.streaming.protocol import (
    TAG_AUDIO_IN,
    TAG_AUDIO_OUT,
    TAG_VIDEO_IN,
    AudioStartMsg,
    ByeMsg,
    CancelMsg,
    EndOfTurnMsg,
    HelloMsg,
    SystemOverrideMsg,
    TextDeltaMsg,
    TurnEndMsg,
    is_audio_in,
    is_video_in,
    pack_audio_out,
    parse_inbound,
    unpack_binary,
)


def test_pack_audio_out_round_trip() -> None:
    pcm = np.array([0, 100, -200, 32767, -32768], dtype=np.int16)
    framed = pack_audio_out(pcm)
    assert framed[0] == TAG_AUDIO_OUT
    body = framed[1:]
    back = np.frombuffer(body, dtype="<i2")
    assert np.array_equal(back, pcm)


def test_pack_audio_out_rejects_non_int16() -> None:
    with pytest.raises(TypeError):
        pack_audio_out(np.array([0.1, 0.2], dtype=np.float32))


def test_unpack_binary_splits_tag() -> None:
    tag, payload = unpack_binary(bytes([TAG_AUDIO_IN, 1, 2, 3]))
    assert tag == TAG_AUDIO_IN
    assert payload == bytes([1, 2, 3])
    assert is_audio_in(tag) and not is_video_in(tag)


def test_unpack_binary_empty_raises() -> None:
    with pytest.raises(ValueError):
        unpack_binary(b"")


def test_parse_hello_message() -> None:
    msg = parse_inbound(json.dumps({"type": "hello", "session_id": "abc", "video_fps": 4}))
    assert isinstance(msg, HelloMsg)
    assert msg.video_fps == 4 and msg.session_id == "abc"


def test_parse_rejects_wrong_sample_rate() -> None:
    with pytest.raises(ValidationError):
        parse_inbound(json.dumps({"type": "hello", "sample_rate": 48000}))


def test_parse_each_inbound_type() -> None:
    assert isinstance(parse_inbound(json.dumps({"type": "end_of_turn"})), EndOfTurnMsg)
    assert isinstance(parse_inbound(json.dumps({"type": "cancel"})), CancelMsg)
    assert isinstance(
        parse_inbound(json.dumps({"type": "system", "prompt": "be brief"})),
        SystemOverrideMsg,
    )
    assert isinstance(parse_inbound(json.dumps({"type": "bye"})), ByeMsg)


def test_parse_unknown_type_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_inbound(json.dumps({"type": "nope"}))


def test_outbound_models_serialize() -> None:
    raw = TextDeltaMsg(turn_id="t1", text="hi").to_json()
    obj = json.loads(raw)
    assert obj == {"type": "text.delta", "turn_id": "t1", "text": "hi"}

    raw = AudioStartMsg(turn_id="t1", sample_rate=24000).to_json()
    assert json.loads(raw)["sample_rate"] == 24000

    raw = TurnEndMsg(turn_id="t1", reason="complete").to_json()
    assert json.loads(raw)["reason"] == "complete"


def test_video_in_tag_recognised() -> None:
    tag, payload = unpack_binary(bytes([TAG_VIDEO_IN]) + b"jpegdata")
    assert tag == TAG_VIDEO_IN
    assert is_video_in(tag)
    assert payload == b"jpegdata"


def test_validate_jpeg_accepts_valid_markers() -> None:
    from vision_asst.streaming.protocol import validate_jpeg

    assert validate_jpeg(b"\xff\xd8" + b"\x00" * 16 + b"\xff\xd9")


def test_validate_jpeg_rejects_missing_markers() -> None:
    from vision_asst.streaming.protocol import validate_jpeg

    assert not validate_jpeg(b"not jpeg data here")
    assert not validate_jpeg(b"\xff\xd8only soi")
    assert not validate_jpeg(b"")


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_inbound(json.dumps({"type": "cancel", "extra": "no"}))
    with pytest.raises(ValidationError):
        parse_inbound(json.dumps({"type": "hello", "session_id": "s1", "unexpected": 1}))


def test_hello_session_id_length_capped() -> None:
    too_long = "x" * 200
    with pytest.raises(ValidationError):
        parse_inbound(json.dumps({"type": "hello", "session_id": too_long}))


def test_hello_video_fps_range_enforced() -> None:
    with pytest.raises(ValidationError):
        parse_inbound(json.dumps({"type": "hello", "video_fps": 0}))
    with pytest.raises(ValidationError):
        parse_inbound(json.dumps({"type": "hello", "video_fps": 100}))
