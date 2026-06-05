"""Vision Assistant — Gemini Live API Relay Server

Bridges hardware (ESP32) and web browser clients to the Gemini Live API.

Endpoints:
    GET  /           → res/index.html  (web test client)
    GET  /res/*      → static files    (res/ directory)
    WS   /ws/device  → ESP32 binary protocol
    WS   /ws/web     → Browser JSON protocol

Binary protocol  (device ↔ server):
    ESP32  → Server : [0x01][PCM 16 kHz 16-bit mono raw bytes]
    ESP32  → Server : [0x02][JPEG bytes]
    Server → ESP32  : [0x01][PCM 24 kHz 16-bit mono raw bytes]

JSON protocol  (browser ↔ server):
    Browser → Server : {"type":"audio","data":"<base64 pcm 16 kHz>"}
    Browser → Server : {"type":"video","data":"<base64 jpeg>"}
    Server → Browser : {"type":"audio","data":"<base64 pcm 24 kHz>"}
    Server → Browser : {"type":"transcript","role":"input"|"output","text":"..."}
    Server → Browser : {"type":"interrupted"}

Config:
    API key  : .env  →  gemini.key  (falls back to default.env)
    System prompt : ASSISTANT.md  (auto-reloaded at startup)

Run:
    uv run python server.py
    # or
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import base64
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types

# ─── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _read_env_key(key: str) -> str:
    """Read a value from .env (falls back to default.env)."""
    for candidate in (BASE_DIR / ".env", BASE_DIR / "default.env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip()
    return ""


GEMINI_API_KEY: str = _read_env_key("gemini.key")
SYSTEM_PROMPT: str = (BASE_DIR / "ASSISTANT.md").read_text(encoding="utf-8")

# ─── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-3.1-flash-live-preview"
MIC_MIME = "audio/pcm;rate=16000"
CAM_MIME = "image/jpeg"

MSG_AUDIO: int = 0x01
MSG_VIDEO: int = 0x02

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Ephemeral auth tokens are only served on the v1alpha API surface, so use a
# dedicated client pinned to that version for minting them.
token_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(api_version="v1alpha"),
)

LIVE_CONFIG = types.LiveConnectConfig(
    response_modalities=[types.Modality.AUDIO],
    system_instruction=types.Content(parts=[types.Part(text=SYSTEM_PROMPT)]),
    # Low temperature keeps guidance accurate and consistent over creative.
    temperature=0.3,
    output_audio_transcription=types.AudioTranscriptionConfig(),
    input_audio_transcription=types.AudioTranscriptionConfig(),
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
        )
    ),
)

# ─── App ───────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Vision Assistant — Gemini Relay")

# The web/Android client may be served from a different origin (e.g. an in-app
# http://localhost server), so allow cross-origin token requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/res", StaticFiles(directory=BASE_DIR / "res"), name="res")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "res" / "index.html")


@app.get("/token")
async def create_token() -> dict[str, str]:
    """Mint a short-lived Gemini ephemeral token for direct client→Live API use.

    The token is locked to our model + LiveConnectConfig (system prompt, audio,
    voice) so the client cannot change them, and is single-use for one new
    session. The Gemini API key never leaves the server.
    """
    token = await token_client.aio.auth_tokens.create(
        config=types.CreateAuthTokenConfig(
            uses=1,
            live_connect_constraints=types.LiveConnectConstraints(
                model=GEMINI_MODEL,
                config=LIVE_CONFIG,
            ),
        )
    )
    return {"token": token.name or ""}


# ─── Internal helpers ──────────────────────────────────────────────────────────
def _to_bytes(data: bytes | str) -> bytes:
    return data if isinstance(data, bytes) else base64.b64decode(data)


def _to_b64(data: bytes | str) -> str:
    return base64.b64encode(data).decode() if isinstance(data, bytes) else data


async def _cancel(*tasks: asyncio.Task) -> None:
    for t in tasks:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, WebSocketDisconnect, Exception):
            pass


# ─── /ws/device  (ESP32 binary protocol) ───────────────────────────────────────
@app.websocket("/ws/device")
async def ws_device(ws: WebSocket) -> None:
    await ws.accept()
    log.info("Device connected  %s", ws.client)

    try:
        async with gemini_client.aio.live.connect(
            model=GEMINI_MODEL, config=LIVE_CONFIG
        ) as session:

            async def _gemini_to_device() -> None:
                async for response in session.receive():
                    content = response.server_content
                    if not content:
                        continue
                    if content.model_turn:
                        for part in content.model_turn.parts:
                            if part.inline_data:
                                payload = bytes([MSG_AUDIO]) + _to_bytes(part.inline_data.data)
                                await ws.send_bytes(payload)

            async def _device_to_gemini() -> None:
                async for data in ws.iter_bytes():
                    if len(data) < 2:
                        continue
                    msg_type, payload = data[0], data[1:]
                    if msg_type == MSG_AUDIO:
                        await session.send_realtime_input(
                            audio=types.Blob(data=payload, mime_type=MIC_MIME)
                        )
                    elif msg_type == MSG_VIDEO:
                        await session.send_realtime_input(
                            video=types.Blob(data=payload, mime_type=CAM_MIME)
                        )

            t1 = asyncio.create_task(_gemini_to_device())
            t2 = asyncio.create_task(_device_to_gemini())
            _, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
            await _cancel(*pending)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.exception("Device session error: %s", exc)

    log.info("Device disconnected  %s", ws.client)


# ─── /ws/web  (Browser JSON protocol) ─────────────────────────────────────────
@app.websocket("/ws/web")
async def ws_web(ws: WebSocket) -> None:
    await ws.accept()
    log.info("Web client connected  %s", ws.client)

    try:
        async with gemini_client.aio.live.connect(
            model=GEMINI_MODEL, config=LIVE_CONFIG
        ) as session:

            async def _gemini_to_web() -> None:
                """Forward Gemini responses to browser indefinitely.

                The Gemini receive() generator ends after each turn, so we
                wrap it in a while-loop to keep the session alive between turns.
                """
                while True:
                    async for response in session.receive():
                        content = response.server_content
                        if not content:
                            continue
                        if content.model_turn:
                            for part in content.model_turn.parts:
                                if part.inline_data:
                                    await ws.send_json(
                                        {"type": "audio", "data": _to_b64(part.inline_data.data)}
                                    )
                        if content.output_transcription:
                            await ws.send_json(
                                {
                                    "type": "transcript",
                                    "role": "output",
                                    "text": content.output_transcription.text,
                                }
                            )
                        if content.input_transcription:
                            await ws.send_json(
                                {
                                    "type": "transcript",
                                    "role": "input",
                                    "text": content.input_transcription.text,
                                }
                            )
                        if content.interrupted:
                            await ws.send_json({"type": "interrupted"})
                    # Gemini turn finished — yield briefly then wait for next turn
                    await asyncio.sleep(0.05)

            async def _web_to_gemini() -> None:
                async for msg in ws.iter_json():
                    msg_type = msg.get("type")
                    if msg_type == "audio":
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=base64.b64decode(msg["data"]), mime_type=MIC_MIME
                            )
                        )
                    elif msg_type == "video":
                        await session.send_realtime_input(
                            video=types.Blob(
                                data=base64.b64decode(msg["data"]), mime_type=CAM_MIME
                            )
                        )

            t1 = asyncio.create_task(_gemini_to_web())
            t2 = asyncio.create_task(_web_to_gemini())
            # Wait only for t2 (browser→Gemini): it ends when browser disconnects.
            # t1 loops indefinitely until cancelled.
            await t2
            await _cancel(t1)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.exception("Web session error: %s", exc)

    log.info("Web client disconnected  %s", ws.client)


# ─── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Vision Assistant — Gemini Live API Relay Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=12345, help="Port to bind (default: 12345)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on file changes")
    args = parser.parse_args()

    uvicorn.run("server:app", host=args.host, port=args.port, reload=args.reload, log_level="info")
