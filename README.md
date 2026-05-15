# Vision Assistant
vision-asst — Real-time Vision Assistant for the Visually Impaired


## Client Set-up

### Install
```bash
# Cli Installation
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh

# ESP32 Board Configuration
arduino-cli config init
arduino-cli config add board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

### Compile Check
```bash
arduino-cli compile --fqbn esp32:esp32:esp32 ./src/client/
```


## Server Set-up
```bash

```

### Archtecture

FastAPI WebSocket server that fronts an embedded vllm-omni
`Qwen3-Omni-30B-A3B-Instruct` MoE model on two RTX Pro 5000 Blackwell GPUs.
Clients stream microphone PCM and camera JPEG frames over a single
WebSocket; the server streams synthesized speech back as PCM chunks with
turn-level barge-in.

```
                    ┌──────────────────────────────────────┐
                    │        vision-asst (one process)     │
  WebSocket ◀───▶   │  FastAPI ─▶ WsSession ─▶ OmniEngine  │
  (PCM/JPEG/JSON)   │              │           (vllm-omni  │
                    │              ▼            AsyncLLM)  │
                    │           VAD + frame buf            │
                    └──────────────────────────────────────┘
                                   │
                                   ▼   tensor_parallel_size=2
                            GPU 0  +  GPU 1
```

Single Python process — `python -m vision_asst` boots Uvicorn; FastAPI's
lifespan loads the omni engine on both GPUs and only opens `/ws` after
`/health` reports `ready`.

### Requirements

- 2 × RTX Pro 5000 Blackwell (Tensor parallel = 2)
- Python ≥ 3.12, CUDA 12.x
- Dependencies are pinned in `pyproject.toml`; install with `uv sync` or
  `pip install -e .[dev]`.

### Running

```bash
# 1. install deps
uv sync

# 2. boot the server (defaults bind 0.0.0.0:8000 on GPUs 0,1)
./run.sh                      # or: uv run python -m vision_asst

# 3. wait for /health to return 200
curl http://localhost:8000/health
```

Override defaults via `VA_*` env vars or CLI flags — see `configs/default.env`
and `./run.sh --help`.

### WebSocket protocol (`/ws`)

### Client → server
- **Binary** frames have a tag byte then payload:
  - `0x01` — PCM16 mono LE @ 16 kHz (microphone audio)
  - `0x02` — JPEG image (camera frame)
- **Text** frames are JSON control messages:

| `type`           | Effect                                                         |
| ---------------- | -------------------------------------------------------------- |
| `hello`          | Optional handshake. `{type, session_id?, sample_rate, video_fps}` |
| `end_of_turn`    | Force a turn boundary (in addition to VAD-detected silence)    |
| `cancel`         | Abort the in-flight generation                                 |
| `system`         | `{type, prompt}` — override the system prompt for the session  |
| `bye`            | Close the session                                              |

#### Server → client
- **Binary**: tag `0x81` then PCM16 mono LE @ 24 kHz audio chunks.
- **Text** JSON messages:

| `type`        | Payload                                                    |
| ------------- | ---------------------------------------------------------- |
| `ready`       | `{model, sample_rate_in, sample_rate_out}`                 |
| `turn.start`  | `{turn_id}`                                                |
| `text.delta`  | `{turn_id, text}` (streaming caption)                      |
| `audio.start` | `{turn_id, sample_rate}`                                   |
| `audio.end`   | `{turn_id}`                                                |
| `turn.end`    | `{turn_id, reason: complete\|cancelled\|interrupted\|error}` |
| `error`       | `{code, message}`                                          |

#### Always-on duplex with barge-in

The server runs WebRTC VAD on the inbound audio stream. After ≥ `MIN_VOICED_MS`
of voiced audio followed by ≥ `SILENCE_MS` of silence, the buffered audio
plus the most recent JPEG frames (sampled across `FRAME_WINDOW_MS`) are
submitted to the model.

If the user starts speaking again while the model is still streaming back,
the active request is aborted (`engine.abort`) and a fresh turn starts —
clients should treat any remaining `0x81` audio bytes after `turn.end
reason=interrupted` as stale.

### Configuration

All tunables are environment variables prefixed with `VA_`. The most
important ones:

| Variable                     | Default                              | Notes                                |
| ---------------------------- | ------------------------------------ | ------------------------------------ |
| `VA_MODEL`                   | `Qwen/Qwen3-Omni-30B-A3B-Instruct`   | HF id or local path                  |
| `VA_TP_SIZE`                 | `2`                                  | matches `CUDA_VISIBLE_DEVICES`       |
| `VA_GPU_MEMORY_UTILIZATION`  | `0.85`                               |                                      |
| `VA_MAX_MODEL_LEN`           | `32768`                              |                                      |
| `VA_HOST` / `VA_PORT`        | `0.0.0.0` / `8000`                   |                                      |
| `VA_VAD_AGGRESSIVENESS`      | `2`                                  | 0 (loose) – 3 (strict)               |
| `VA_SILENCE_MS`              | `300`                                | trailing silence to end a turn       |
| `VA_MIN_VOICED_MS`           | `250`                                | voiced audio to start a turn         |
| `VA_MAX_FRAMES_PER_TURN`     | `4`                                  | JPEG frames included per request     |
| `VA_SYSTEM_PROMPT`           | (Korean default in `config.py`)      |                                      |
| `VA_MAX_CONCURRENT_WS`       | `8`                                  | reject new sockets past this         |
| `VA_IDLE_TIMEOUT_S`          | `300`                                | close sockets that fall silent       |
| `VA_WS_MAX_SIZE`             | `1048576` (1 MiB)                    | per-frame envelope cap               |

#### Per-frame protocol limits (enforced server-side)

| Frame type   | Cap          | What happens on overflow                |
| ------------ | ------------ | --------------------------------------- |
| Audio (PCM)  | 32 000 bytes | `error frame_too_large` then disconnect |
| Video (JPEG) | 512 KiB      | `error bad_jpeg` (frame dropped)        |
| Text (JSON)  | 16 KiB       | `error text_too_large` (frame dropped)  |

JPEGs are also lightly validated (SOI/EOI markers) before being buffered.

### Deployment

This service ships **without** authentication, TLS, or origin checks — put
it behind a reverse proxy (nginx, Caddy, Traefik) that:

1. Terminates TLS.
2. Validates `Origin` against your allowlist for browser clients.
3. Enforces auth (mTLS, OAuth, API key — whichever fits).
4. Rate-limits connections per IP to back up the in-process `VA_MAX_CONCURRENT_WS`.

Run `pip-audit` against `vllm`, `vllm-omni`, `transformers`, and `torch`
before exposing the service publicly:

```bash
uv pip install pip-audit && uv run pip-audit -r <(uv export --no-emit-project)
```

### Testing

```bash
uv run pytest -q          # unit tests (CPU only — engine is faked)
uv run ruff check .
```

Tests cover the WebSocket framing, audio ring buffer, WebRTC VAD wrapper,
JPEG frame buffer, and a full session lifecycle (turn → cancel → bye)
driven by `FakeOmniEngine`.

### Layout

```
src/vision_asst/
├── app.py              FastAPI factory + lifespan
├── config.py           Pydantic settings (VA_*)
├── __main__.py         python -m vision_asst entrypoint
├── engine/
│   ├── omni_engine.py  vllm-omni AsyncLLMEngine wrapper
│   └── prompt.py       Qwen3-Omni chat-message builder
├── streaming/
│   ├── protocol.py     Binary tags + JSON message models
│   ├── audio.py        PCM16 ring buffer
│   ├── vad.py          webrtcvad-based turn detector
│   ├── video.py        time-windowed JPEG buffer
│   └── session.py      Per-connection orchestrator
└── routes/
    ├── http.py         /health, /info
    └── ws.py           /ws
```
