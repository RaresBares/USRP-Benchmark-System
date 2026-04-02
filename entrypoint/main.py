import os
import uuid
import json
import asyncio
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Query, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse
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


def _validate_token(auth_token, db):
    token = db.query(Token).filter(Token.token == auth_token).first()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid auth token")
    return token


def _check_queue(db):
    return db.query(Task).filter(Task.state.in_(("PD", "R"))).count() < MAX_PENDING


async def _read_upload(upload):
    data = await upload.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE} bytes)")
    return data


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
        await _ws_send(ws, message="queued", uid=str(task_uid), state="PD")

        while True:
            await asyncio.sleep(2)
            db.refresh(task)
            await _ws_send(ws, message="status", uid=str(task_uid), state=task.state)
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


# ── REST fallback ──

@app.post("/upload/f32")
async def upload_f32(
    request: Request,
    f32_file: UploadFile = File(...),
    auth_token: str = Query(...),
    db: Session = Depends(get_db),
):
    token = _validate_token(auth_token, db)
    ip = request.client.host if request.client else None
    if not _check_queue(db):
        _log(db, "rest_queue_full", token_id=token.id, ip=ip)
        raise HTTPException(status_code=503, detail="Queue full, try again later")
    data = await _read_upload(f32_file)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "input.f32").write_bytes(data)
    task = Task(uid=task_uid, token_id=token.id)
    db.add(task)
    db.commit()
    _log(db, "rest_upload", token_id=token.id, ip=ip, detail=f"uid={task_uid} size={len(data)}")
    return {"uid": str(task_uid), "state": "PD"}


@app.get("/state/{task_uid}")
def get_state(task_uid: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.uid == task_uid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    ip = request.client.host if request.client else None
    _log(db, "rest_state", token_id=task.token_id, ip=ip, detail=f"uid={task_uid}")
    return {
        "uid": str(task.uid),
        "state": task.state,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "done_at": task.done_at.isoformat() if task.done_at else None,
        "error": task.error_message,
    }


@app.get("/download/f32/{task_uid}")
def download_f32(task_uid: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.uid == task_uid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.state != "D":
        raise HTTPException(status_code=409, detail="Task not done yet")
    f32_path = OUTPUT_DIR / str(task_uid) / "output.f32"
    if not f32_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    ip = request.client.host if request.client else None
    _log(db, "rest_download", token_id=task.token_id, ip=ip, detail=f"uid={task_uid}")
    return FileResponse(f32_path, media_type="application/octet-stream", filename="output.f32")
