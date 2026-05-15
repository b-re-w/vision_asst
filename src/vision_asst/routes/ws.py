"""WebSocket endpoint that hands off to a :class:`WsSession`."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from ..streaming.session import WsSession, WsTransport

log = logging.getLogger(__name__)
router = APIRouter()


class _StarletteTransport:
    """Adapt a Starlette ``WebSocket`` to :class:`WsTransport`."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def receive(self) -> dict:
        return await self._ws.receive()

    async def send_text(self, data: str) -> None:
        await self._ws.send_text(data)

    async def send_bytes(self, data: bytes) -> None:
        await self._ws.send_bytes(data)

    async def close(self, code: int = 1000) -> None:
        try:
            await self._ws.close(code=code)
        except Exception as exc:
            log.debug("ws.close(%s) failed: %s", code, exc)


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    app = websocket.app
    engine = getattr(app.state, "engine", None)
    if engine is None or not engine.is_ready():
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    sem: asyncio.Semaphore = app.state.ws_sem
    if sem.locked():
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    settings = app.state.settings
    await websocket.accept()
    transport: WsTransport = _StarletteTransport(websocket)
    session = WsSession(ws=transport, engine=engine, settings=settings)
    async with sem:
        try:
            await session.run()
        except WebSocketDisconnect:
            log.info("client disconnected")
        except Exception as exc:
            log.exception("websocket session crashed: %s", exc)
        finally:
            try:
                await websocket.close()
            except Exception as exc:
                log.debug("final ws.close failed: %s", exc)
