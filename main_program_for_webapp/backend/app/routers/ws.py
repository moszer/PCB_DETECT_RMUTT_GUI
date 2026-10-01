"""WebSocket router for real-time machine state, scan progress, and event stream."""
import asyncio
import json
import logging
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.aoi_scan_service import aoi_scan_service
from ..services.dataset_service import dataset_service
from ..services.machine_service import machine_service

logger = logging.getLogger("ws_router")
router = APIRouter(tags=["websocket"])

active_connections: Set[WebSocket] = set()


async def broadcast_json(data: dict):
    msg = json.dumps(data)
    for ws in list(active_connections):
        try:
            await ws.send_text(msg)
        except Exception:
            active_connections.discard(ws)


# Hook up synchronous machine and aoi services to WebSocket broadcaster
loop: asyncio.AbstractEventLoop = None


def _on_machine_state(state):
    global loop
    if loop and loop.is_running() and active_connections:
        asyncio.run_coroutine_threadsafe(
            broadcast_json({"type": "machine_state", "data": state.model_dump()}),
            loop
        )


def _on_scan_progress(payload):
    global loop
    if loop and loop.is_running() and active_connections:
        asyncio.run_coroutine_threadsafe(
            broadcast_json({"type": "scan_progress", "data": payload}),
            loop
        )


def _on_dataset_progress(payload):
    if loop and loop.is_running() and active_connections:
        asyncio.run_coroutine_threadsafe(broadcast_json({"type": "dataset_progress", "data": payload}), loop)


machine_service.subscribe(_on_machine_state)
aoi_scan_service.subscribe_progress(_on_scan_progress)
dataset_service.subscribe(_on_dataset_progress)


@router.websocket("/ws/status")
async def websocket_status_endpoint(websocket: WebSocket):
    global loop
    loop = asyncio.get_running_loop()

    await websocket.accept()
    active_connections.add(websocket)
    logger.info("WebSocket client connected. Total clients: %d", len(active_connections))

    try:
        # Send initial state snapshot
        await websocket.send_json({
            "type": "machine_state",
            "data": machine_service.get_state().model_dump()
        })
        if aoi_scan_service.current_run:
            await websocket.send_json({
                "type": "scan_progress",
                "data": {"event": "active_run", "report": aoi_scan_service.current_run.model_dump()}
            })

        while True:
            # Keep connection alive and accept incoming pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.discard(websocket)
        logger.info("WebSocket client disconnected. Remaining: %d", len(active_connections))
