"""Minimal WebSocket client for the vision-asst server.

Streams a WAV file (or microphone PCM, if you swap it in) and a single
JPEG frame to ``ws://HOST:PORT/ws``, prints incoming text deltas, and
writes the streamed audio response to ``out.wav``.

Usage::

    python examples/ws_client.py path/to/utterance.wav path/to/frame.jpg \\
        --url ws://localhost:8000/ws

The WAV must be PCM16 mono @ 16 kHz. Use ``ffmpeg -i in.mp3 -ac 1 -ar
16000 -sample_fmt s16 utterance.wav`` to convert if needed.

Requires ``websockets`` and ``soundfile``::

    uv pip install websockets soundfile
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import wave
from pathlib import Path

try:
    import websockets
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install websockets first: uv pip install websockets") from exc


CHUNK_MS = 100  # 100 ms ≈ 1600 samples @ 16 kHz
INPUT_SR = 16000
OUTPUT_SR = 24000

# Mirror the server's binary tags.
TAG_AUDIO_IN = 0x01
TAG_VIDEO_IN = 0x02
TAG_AUDIO_OUT = 0x81


def _read_pcm16_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise SystemExit(f"{path} must be PCM16 mono")
        if wf.getframerate() != INPUT_SR:
            raise SystemExit(
                f"{path} sample rate is {wf.getframerate()} Hz; expected {INPUT_SR}"
            )
        return wf.readframes(wf.getnframes())


async def _send_audio(ws, pcm: bytes) -> None:
    samples_per_chunk = INPUT_SR * CHUNK_MS // 1000
    bytes_per_chunk = samples_per_chunk * 2
    for i in range(0, len(pcm), bytes_per_chunk):
        chunk = pcm[i : i + bytes_per_chunk]
        await ws.send(bytes([TAG_AUDIO_IN]) + chunk)
        await asyncio.sleep(CHUNK_MS / 1000)


async def _recv_loop(ws, out_path: Path) -> None:
    received = bytearray()
    async for msg in ws:
        if isinstance(msg, bytes):
            if msg and msg[0] == TAG_AUDIO_OUT:
                received.extend(msg[1:])
        else:
            try:
                obj = json.loads(msg)
            except json.JSONDecodeError:
                continue
            t = obj.get("type")
            if t == "text.delta":
                print(obj.get("text", ""), end="", flush=True)
            elif t == "turn.end":
                print()
                print(f"<turn.end reason={obj.get('reason')}>")
                break
            elif t == "error":
                print(f"<error {obj.get('code')}: {obj.get('message')}>", file=sys.stderr)
                break
            elif t == "ready":
                print(f"<ready model={obj.get('model')}>")

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(OUTPUT_SR)
        wf.writeframes(bytes(received))
    print(f"wrote {len(received) // 2} samples to {out_path}")


async def main(args: argparse.Namespace) -> None:
    pcm = _read_pcm16_wav(Path(args.audio))
    jpeg = Path(args.image).read_bytes() if args.image else None

    async with websockets.connect(args.url, max_size=64 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "hello", "sample_rate": INPUT_SR, "video_fps": 1}))
        if jpeg is not None:
            await ws.send(bytes([TAG_VIDEO_IN]) + jpeg)
        send_task = asyncio.create_task(_send_audio(ws, pcm))
        recv_task = asyncio.create_task(_recv_loop(ws, Path(args.out)))
        await send_task
        await ws.send(json.dumps({"type": "end_of_turn"}))
        await recv_task
        await ws.send(json.dumps({"type": "bye"}))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("audio", help="Path to PCM16 mono 16 kHz WAV")
    p.add_argument("image", nargs="?", default=None, help="Optional JPEG frame")
    p.add_argument("--url", default="ws://localhost:8000/ws")
    p.add_argument("--out", default="out.wav", help="Where to write the response audio")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
