"""Health and info HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    engine = getattr(request.app.state, "engine", None)
    settings = request.app.state.settings
    if engine is None or not engine.is_ready():
        return JSONResponse(
            {"status": "loading", "model": settings.model, "tp": settings.tp_size},
            status_code=503,
        )
    return JSONResponse(
        {"status": "ready", "model": engine.model_name, "tp": settings.tp_size}
    )


@router.get("/info")
async def info(request: Request) -> dict:
    s = request.app.state.settings
    engine = getattr(request.app.state, "engine", None)
    return {
        "model": s.model,
        "tp": s.tp_size,
        "gpu_count": s.tp_size,
        "max_model_len": s.max_model_len,
        "input_sr": s.input_sr,
        "output_sr": s.output_sr,
        "video_fps_max": s.video_fps_max,
        "max_frames_per_turn": s.max_frames_per_turn,
        "frame_window_ms": s.frame_window_ms,
        "vad_aggressiveness": s.vad_aggressiveness,
        "silence_ms": s.silence_ms,
        "min_voiced_ms": s.min_voiced_ms,
        "max_concurrent_ws": s.max_concurrent_ws,
        "ready": engine.is_ready() if engine is not None else False,
    }
