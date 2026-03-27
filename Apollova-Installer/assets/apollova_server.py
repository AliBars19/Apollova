"""
Apollova Mobile Server — FastAPI backend for remote control via iOS app.

Runs as a daemon thread inside the Apollova GUI process. Shares state directly
with the GUI via a reference — no IPC, everything in-process.

Endpoints: see ROUTES table below.
Auth: Bearer token from settings.json (generated on first Mobile Connect setup).
"""

import os
import sys
import json
import hmac
import asyncio
import secrets
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------------------------------------------------------
#  Globals — set by the GUI at startup
# ---------------------------------------------------------------------------
_gui_ref = None          # Reference to AppolovaApp instance
_settings_file = None    # Path to settings.json
_settings = {}           # Cached settings dict

server_event_loop: Optional[asyncio.AbstractEventLoop] = None
active_ws_clients: list[WebSocket] = []


def set_gui_ref(gui, settings_path: str = None):
    """Called once from apollova_gui.py __init__ to wire the server to the GUI."""
    global _gui_ref, _settings_file, _settings
    _gui_ref = gui
    if settings_path:
        _settings_file = Path(settings_path)
    else:
        # Derive from GUI's SETTINGS_FILE constant
        _settings_file = getattr(gui, '_settings_file_path', None)
        if _settings_file is None:
            if getattr(sys, "frozen", False):
                _settings_file = Path(sys.executable).parent / "settings.json"
            else:
                _settings_file = Path(__file__).parent.parent / "settings.json"
    _settings = _load_settings()


def _load_settings() -> dict:
    if _settings_file and _settings_file.exists():
        try:
            return json.loads(_settings_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_settings(data: dict):
    global _settings
    _settings = data
    if _settings_file:
        _settings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _get_session_token() -> str:
    """Return the current session token, generating one if missing."""
    token = _settings.get("session_token")
    if not token:
        token = secrets.token_hex(32)
        _settings["session_token"] = token
        _save_settings(_settings)
    return token


# ---------------------------------------------------------------------------
#  Auth Middleware
# ---------------------------------------------------------------------------
class AuthMiddleware(BaseHTTPMiddleware):
    """Require Bearer token on all routes except /health and /qr."""

    EXEMPT_PATHS = {"/health", "/docs", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {_get_session_token()}"

        if not hmac.compare_digest(auth, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
#  FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="Apollova Mobile API", version="1.0.0")
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
#  Startup — capture the event loop for thread-safe broadcasting
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _capture_loop():
    global server_event_loop
    server_event_loop = asyncio.get_running_loop()


# ---------------------------------------------------------------------------
#  WebSocket broadcast helpers (thread-safe)
# ---------------------------------------------------------------------------
async def _broadcast(event: dict):
    dead = []
    for ws in active_ws_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_ws_clients.remove(ws)


def emit_progress(percent: float, message: str):
    """Called from the GUI thread to push progress to all WebSocket clients."""
    if server_event_loop and active_ws_clients:
        asyncio.run_coroutine_threadsafe(
            _broadcast({"type": "progress", "percent": percent, "message": message}),
            server_event_loop,
        )


def emit_event(event: dict):
    """Generic event broadcaster — called from GUI thread."""
    if server_event_loop and active_ws_clients:
        asyncio.run_coroutine_threadsafe(_broadcast(event), server_event_loop)


# ---------------------------------------------------------------------------
#  Routes
# ---------------------------------------------------------------------------

# ── Health (no auth) ─────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ── Status ───────────────────────────────────────────────────────────────────
@app.get("/status")
async def status():
    gui = _gui_ref
    if not gui:
        return {"error": "GUI not initialised"}

    tunnel_url = _settings.get("tunnel_url")
    return {
        "is_processing": getattr(gui, "is_processing", False),
        "cancel_requested": getattr(gui, "cancel_requested", False),
        "batch_render_active": getattr(gui, "batch_render_active", False),
        "tunnel_url": tunnel_url,
        "template": _settings.get("template", "aurora"),
        "mobile_enabled": _settings.get("mobile_enabled", True),
    }


# ── Database ─────────────────────────────────────────────────────────────────
@app.get("/database")
async def database_list():
    gui = _gui_ref
    if not gui or not gui.song_db:
        raise HTTPException(500, "Database not available")

    songs = gui.song_db.list_all_songs()
    return {"songs": songs, "total": len(songs)}


@app.post("/database/add")
async def database_add(request: Request):
    gui = _gui_ref
    if not gui or not gui.song_db:
        raise HTTPException(500, "Database not available")

    body = await request.json()
    title = body.get("title", "").strip()
    url = body.get("url", "").strip()
    start = body.get("start", "0:00").strip()
    end = body.get("end", "0:30").strip()

    if not title or not url:
        raise HTTPException(400, "title and url are required")

    gui.song_db.add_song(
        song_title=title, youtube_url=url,
        start_time=start, end_time=end,
        genius_image_url=None, colors=None, beats=None,
    )
    return {"status": "added", "title": title}


@app.delete("/database/{song_id}")
async def database_delete(song_id: int):
    gui = _gui_ref
    if not gui or not gui.song_db:
        raise HTTPException(500, "Database not available")

    gui.song_db.delete_song(song_id)
    return {"status": "deleted", "id": song_id}


# ── Jobs ─────────────────────────────────────────────────────────────────────
@app.get("/jobs")
async def jobs_list():
    gui = _gui_ref
    if not gui:
        raise HTTPException(500, "GUI not available")

    from apollova_gui import JOBS_DIRS
    jobs = []
    for template, jobs_dir in JOBS_DIRS.items():
        if not jobs_dir.exists():
            continue
        for job_dir in sorted(jobs_dir.glob("job_*"), reverse=True):
            data_file = job_dir / "job_data.json"
            status = "complete" if data_file.exists() else "incomplete"
            info = {"folder": job_dir.name, "template": template, "status": status}
            if data_file.exists():
                try:
                    data = json.loads(data_file.read_text(encoding="utf-8"))
                    info["song_title"] = data.get("song_title", "")
                except Exception:
                    pass
            jobs.append(info)
    return {"jobs": jobs, "total": len(jobs)}


@app.post("/jobs/generate")
async def jobs_generate(request: Request):
    gui = _gui_ref
    if not gui:
        raise HTTPException(500, "GUI not available")

    if gui.is_processing:
        raise HTTPException(409, "Batch already in progress")

    body = await request.json()
    mode = body.get("mode", "smart_picker")
    template = body.get("template", "aurora")
    count = body.get("count", 12)
    songs = body.get("songs")

    # Thread-safe: schedule generation on the GUI thread
    def _run():
        gui.use_smart_picker = (mode == "smart_picker")
        if songs:
            gui._job_queue = songs
        gui._start_generation()

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, _run)
    return {"status": "started", "mode": mode, "template": template}


@app.post("/jobs/cancel")
async def jobs_cancel():
    gui = _gui_ref
    if not gui:
        raise HTTPException(500, "GUI not available")

    gui.cancel_requested = True
    return {"status": "cancel_requested"}


@app.post("/jobs/resume")
async def jobs_resume():
    gui = _gui_ref
    if not gui:
        raise HTTPException(500, "GUI not available")

    if gui.is_processing:
        raise HTTPException(409, "Batch already in progress")

    def _run():
        gui._resume_mode = True
        gui._start_generation()

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, _run)
    return {"status": "resume_started"}


# ── Smart Picker ─────────────────────────────────────────────────────────────
@app.get("/smart-picker/preview")
async def smart_picker_preview(shuffle: bool = Query(False)):
    gui = _gui_ref
    if not gui:
        raise HTTPException(500, "GUI not available")

    from scripts.smart_picker import SmartSongPicker
    from apollova_gui import DATABASE_DIR
    picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
    songs = picker.get_available_songs(num_songs=12, shuffle=shuffle)
    return {"songs": songs}


@app.post("/smart-picker/reshuffle")
async def smart_picker_reshuffle():
    gui = _gui_ref
    if not gui:
        raise HTTPException(500, "GUI not available")

    from scripts.smart_picker import SmartSongPicker
    from apollova_gui import DATABASE_DIR
    picker = SmartSongPicker(db_path=str(DATABASE_DIR / "songs.db"))
    songs = picker.get_available_songs(num_songs=12, shuffle=True)
    return {"songs": songs}


# ── Render ───────────────────────────────────────────────────────────────────
@app.post("/render/trigger")
async def render_trigger(request: Request):
    gui = _gui_ref
    if not gui:
        raise HTTPException(500, "GUI not available")

    body = await request.json()
    template = body.get("template", "aurora")

    ae_path = _settings.get("after_effects_path")
    if not ae_path or not Path(ae_path).exists():
        raise HTTPException(409, "After Effects is not running")

    def _run():
        gui._trigger_batch_render(template)

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, _run)
    return {"status": "render_triggered", "template": template}


@app.post("/render/triple")
async def render_triple():
    gui = _gui_ref
    if not gui:
        raise HTTPException(500, "GUI not available")

    ae_path = _settings.get("after_effects_path")
    if not ae_path or not Path(ae_path).exists():
        raise HTTPException(409, "After Effects is not running")

    def _run():
        for t in ["aurora", "mono", "onyx"]:
            gui._trigger_batch_render(t)

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, _run)
    return {"status": "triple_render_triggered"}


@app.get("/render/status")
async def render_status():
    return {"status": "no_active_render", "queue": []}


# ── QR Code ──────────────────────────────────────────────────────────────────
@app.get("/qr")
async def qr_code(new: bool = Query(False)):
    if new:
        _settings["session_token"] = secrets.token_hex(32)
        _save_settings(_settings)

    token = _get_session_token()
    tunnel_url = _settings.get("tunnel_url", "")

    qr_data = json.dumps({"url": tunnel_url, "token": token})

    try:
        import qrcode
        from io import BytesIO
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="white", back_color="#0D0A18")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
    except ImportError:
        return JSONResponse({"qr_data": qr_data, "error": "qrcode package not installed"})


# ── WebSocket: Real-time progress ────────────────────────────────────────────
@app.websocket("/progress")
async def ws_progress(websocket: WebSocket):
    # Auth check for WebSocket
    auth = websocket.headers.get("authorization", "")
    # Also check query param for clients that can't set WS headers
    token_param = websocket.query_params.get("token", "")
    expected = _get_session_token()

    if auth != f"Bearer {expected}" and token_param != expected:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    active_ws_clients.append(websocket)

    try:
        while True:
            # Keep connection alive — client may send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in active_ws_clients:
            active_ws_clients.remove(websocket)
