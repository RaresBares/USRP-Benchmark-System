import os
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Query, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db, engine
from models import Token, Task

app = FastAPI(title="USRP Benchmark System")

DATA_DIR = Path("/data")
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
DEFAULT_TOKEN = os.getenv("DEFAULT_AUTH_TOKEN", "default-bench-token-2024")
MAX_FILE_SIZE = int(os.getenv("MAX_UPLOAD_KB", "50")) * 1024


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


async def _read_upload(upload):
    data = await upload.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE} bytes)")
    return data


def _create_task(db, token, task_uid, task_type):
    task = Task(uid=task_uid, token_id=token.id, task_type=task_type)
    db.add(task)
    db.commit()
    return {"uid": str(task_uid), "type": task_type, "state": "PD"}


@app.post("/upload/f32")
async def upload_f32(f32_file: UploadFile = File(...), auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = _validate_token(auth_token, db)
    data = await _read_upload(f32_file)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "input.f32").write_bytes(data)
    return _create_task(db, token, task_uid, "F32")


@app.post("/upload/py2")
async def upload_py2(in_py: UploadFile = File(...), out_py: UploadFile = File(...), auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = _validate_token(auth_token, db)
    in_data = await _read_upload(in_py)
    out_data = await _read_upload(out_py)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "in.py").write_bytes(in_data)
    (task_dir / "out.py").write_bytes(out_data)
    return _create_task(db, token, task_uid, "PY2")


@app.post("/upload/py2bin")
async def upload_py2bin(in_py: UploadFile = File(...), out_py: UploadFile = File(...), bin_file: UploadFile = File(...), auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = _validate_token(auth_token, db)
    in_data = await _read_upload(in_py)
    out_data = await _read_upload(out_py)
    bin_data = await _read_upload(bin_file)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "in.py").write_bytes(in_data)
    (task_dir / "out.py").write_bytes(out_data)
    (task_dir / "input.bin").write_bytes(bin_data)
    return _create_task(db, token, task_uid, "PY2BIN")


@app.post("/upload/combo")
async def upload_combo(combo_py: UploadFile = File(...), auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = _validate_token(auth_token, db)
    data = await _read_upload(combo_py)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "combo.py").write_bytes(data)
    return _create_task(db, token, task_uid, "COMBO")


@app.post("/upload/combobin")
async def upload_combobin(combo_py: UploadFile = File(...), bin_file: UploadFile = File(...), auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = _validate_token(auth_token, db)
    combo_data = await _read_upload(combo_py)
    bin_data = await _read_upload(bin_file)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "combo.py").write_bytes(combo_data)
    (task_dir / "input.bin").write_bytes(bin_data)
    return _create_task(db, token, task_uid, "COMBOBIN")


@app.post("/upload/oct2")
async def upload_oct2(in_m: UploadFile = File(...), out_m: UploadFile = File(...), auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = _validate_token(auth_token, db)
    in_data = await _read_upload(in_m)
    out_data = await _read_upload(out_m)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "in.m").write_bytes(in_data)
    (task_dir / "out.m").write_bytes(out_data)
    return _create_task(db, token, task_uid, "OCT2")


@app.post("/upload/oct2bin")
async def upload_oct2bin(in_m: UploadFile = File(...), out_m: UploadFile = File(...), bin_file: UploadFile = File(...), auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = _validate_token(auth_token, db)
    in_data = await _read_upload(in_m)
    out_data = await _read_upload(out_m)
    bin_data = await _read_upload(bin_file)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "in.m").write_bytes(in_data)
    (task_dir / "out.m").write_bytes(out_data)
    (task_dir / "input.bin").write_bytes(bin_data)
    return _create_task(db, token, task_uid, "OCT2BIN")


@app.post("/upload/octcombo")
async def upload_octcombo(combo_m: UploadFile = File(...), auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = _validate_token(auth_token, db)
    data = await _read_upload(combo_m)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "combo.m").write_bytes(data)
    return _create_task(db, token, task_uid, "OCTCOMBO")


@app.post("/upload/octcombobin")
async def upload_octcombobin(combo_m: UploadFile = File(...), bin_file: UploadFile = File(...), auth_token: str = Query(...), db: Session = Depends(get_db)):
    token = _validate_token(auth_token, db)
    combo_data = await _read_upload(combo_m)
    bin_data = await _read_upload(bin_file)
    task_uid = uuid.uuid4()
    task_dir = INPUT_DIR / str(task_uid)
    task_dir.mkdir(parents=True)
    (task_dir / "combo.m").write_bytes(combo_data)
    (task_dir / "input.bin").write_bytes(bin_data)
    return _create_task(db, token, task_uid, "OCTCOMBOBIN")


@app.get("/state/{task_uid}")
def get_state(task_uid: uuid.UUID, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.uid == task_uid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "uid": str(task.uid), "state": task.state, "type": task.task_type,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "done_at": task.done_at.isoformat() if task.done_at else None,
        "error": task.error_message,
    }


@app.get("/download/f32/{task_uid}")
def download_f32(task_uid: uuid.UUID, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.uid == task_uid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.state != "D":
        raise HTTPException(status_code=409, detail="Task not done yet")
    f32_path = OUTPUT_DIR / str(task_uid) / "output.f32"
    if not f32_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(f32_path, media_type="application/octet-stream", filename="output.f32")


@app.get("/download/bits/{task_uid}")
def download_bits(task_uid: uuid.UUID, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.uid == task_uid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.state != "D":
        raise HTTPException(status_code=409, detail="Task not done yet")
    if task.task_type == "F32":
        raise HTTPException(status_code=400, detail="Bits download not available for F32 tasks")
    bin_path = OUTPUT_DIR / str(task_uid) / "output.bin"
    if not bin_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(bin_path, media_type="application/octet-stream", filename="output.bin")


@app.get("/download/wave/{task_uid}")
def download_wave(task_uid: uuid.UUID, db: Session = Depends(get_db)):
    return download_f32(task_uid, db)
