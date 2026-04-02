import os
import uuid
import json
import asyncio
from pathlib import Path

from fastapi import FastAPI, Query, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from database import get_db, engine
from models import Token, Task, Log

app = FastAPI(title="USRP Benchmark System")

DATA_DIR = Path("/data")
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
DEFAULT_TOKEN = os.getenv("DEFAULT_AUTH_TOKEN", "default-bench-token-2024")
MAX_FILE_SIZE = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024
MAX_WS = int(os.getenv("MAX_WS_CONNECTIONS", "100"))
MAX_PENDING = int(os.getenv("MAX_PENDING_TASKS", "200"))

RADIO_INFO = {
    "carrier_frequency_hz": int(os.getenv("CARRIER_FREQUENCY_HZ", "2400000000")),
    "sample_rate_hz": int(os.getenv("SAMPLE_RATE_HZ", "20000000")),
    "bandwidth_hz": int(os.getenv("BANDWIDTH_HZ", "20000000")),
    "tx_gain_db": int(os.getenv("TX_GAIN_DB", "30")),
    "rx_gain_db": int(os.getenv("RX_GAIN_DB", "30")),
    "channel_snr_db": float(os.getenv("CHANNEL_SNR_DB", "20")),
    "antenna_tx": os.getenv("ANTENNA_TX", "TX/RX0"),
    "antenna_rx": os.getenv("ANTENNA_RX", "RX1"),
    "max_upload_mb": int(os.getenv("MAX_UPLOAD_MB", "200")),
    "max_samples": int(os.getenv("MAX_SAMPLES", "2500000")),
    "use_real_usrp": os.getenv("USE_REAL_USRP", "false").lower() == "true",
    "duty_cycle_max_percent": float(os.getenv("DUTY_CYCLE_MAX_PERCENT", "10")),
    "duty_cycle_window_sec": float(os.getenv("DUTY_CYCLE_WINDOW_SEC", "60")),
    "lbt_enabled": os.getenv("LBT_ENABLED", "true").lower() == "true",
    "lbt_threshold_dbfs": float(os.getenv("LBT_THRESHOLD_DBFS", "-50")),
}

ws_count = 0


def _log(db, action, token_id=None, detail=None, ip=None):
    db.add(Log(token_id=token_id, action=action, detail=detail, ip=ip))
    db.commit()


@app.on_event("startup")
def startup():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    from sqlalchemy.orm import Session as S
    with S(bind=engine) as db:
        if not db.query(Token).filter(Token.token == DEFAULT_TOKEN).first():
            db.add(Token(token=DEFAULT_TOKEN, label="default", is_default=True))
            db.commit()


def _check_queue(db):
    return db.query(Task).filter(Task.state.in_(("PD", "R"))).count() < MAX_PENDING


def _queue_position(db, task):
    return db.query(Task).filter(
        Task.state == "PD",
        Task.created_at < task.created_at
    ).count()


async def _ws_send(ws, **kwargs):
    await ws.send_text(json.dumps(kwargs))


@app.websocket("/ws/run")
async def ws_run(ws: WebSocket):
    global ws_count

    await ws.accept()
    ws_count += 1

    if ws_count > MAX_WS:
        await _ws_send(ws, error="too_many_connections", message="Server full, try again later")
        await ws.close()
        ws_count -= 1
        return

    db = next(get_db())
    ip = ws.client.host if ws.client else None
    try:
        auth_token = ws.query_params.get("auth_token", "")
        token = db.query(Token).filter(Token.token == auth_token).first()
        if not token:
            _log(db, "ws_auth_failed", ip=ip, detail=f"token={auth_token[:20]}")
            await _ws_send(ws, error="auth_failed", message="Invalid auth token")
            await ws.close()
            return

        await _ws_send(ws, message="info", **RADIO_INFO)

        if not _check_queue(db):
            _log(db, "ws_queue_full", token_id=token.id, ip=ip)
            await _ws_send(ws, error="queue_full", message="Too many pending tasks, try again later")
            await ws.close()
            return

        data = await ws.receive_bytes()
        if len(data) > MAX_FILE_SIZE:
            _log(db, "ws_file_too_large", token_id=token.id, ip=ip, detail=f"{len(data)} bytes")
            await _ws_send(ws, error="file_too_large", message=f"Max {MAX_FILE_SIZE} bytes")
            await ws.close()
            return

        task_uid = uuid.uuid4()
        task_dir = INPUT_DIR / str(task_uid)
        task_dir.mkdir(parents=True)
        (task_dir / "input.f32").write_bytes(data)

        task = Task(uid=task_uid, token_id=token.id)
        db.add(task)
        db.commit()

        _log(db, "ws_upload", token_id=token.id, ip=ip, detail=f"uid={task_uid} size={len(data)}")
        pos = _queue_position(db, task)
        await _ws_send(ws, message="queued", uid=str(task_uid), state="PD", queue_position=pos)

        while True:
            await asyncio.sleep(2)
            db.refresh(task)
            pos = _queue_position(db, task)
            await _ws_send(ws, message="status", uid=str(task_uid), state=task.state, queue_position=pos)
            if task.state == "D":
                break

        if task.error_message:
            _log(db, "ws_task_error", token_id=token.id, ip=ip, detail=f"uid={task_uid}")
            await _ws_send(ws, error="processing_failed", message=task.error_message)
        else:
            f32_path = OUTPUT_DIR / str(task_uid) / "output.f32"
            if f32_path.exists():
                _log(db, "ws_download", token_id=token.id, ip=ip, detail=f"uid={task_uid}")
                await _ws_send(ws, message="done", uid=str(task_uid))
                await ws.send_bytes(f32_path.read_bytes())
            else:
                await _ws_send(ws, error="no_output", message="Output file not found")

        await ws.close()

    except WebSocketDisconnect:
        _log(db, "ws_disconnect", ip=ip)
    finally:
        ws_count -= 1
        db.close()


@app.get("/health")
def health(auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = db.query(Token).filter(Token.token == auth_token).first()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid auth token")
    pending = db.query(Task).filter(Task.state.in_(("PD", "R"))).count()
    return {"status": "ok", "pending_tasks": pending, "ws_connections": ws_count}


@app.get("/info")
def info(auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = db.query(Token).filter(Token.token == auth_token).first()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid auth token")
    return RADIO_INFO
