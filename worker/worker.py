import os
import sys
import time
import shutil
import traceback
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Task
from channel import send_and_receive
from sandbox import run_python_function, run_octave_function

DATA_DIR = Path("/data")
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
DUMMY_BIN = DATA_DIR / "dummy.bin"

POLL_INTERVAL = 2
TASK_TTL_HOURS = int(os.getenv("TASK_TTL_HOURS", "24"))
MAX_SAMPLES = int(os.getenv("MAX_SAMPLES", "100000"))
MAX_OUTPUT_BYTES = int(os.getenv("MAX_OUTPUT_FILE_MB", "10")) * 1024 * 1024


def ensure_dummy_bin():
    if not DUMMY_BIN.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        np.random.randint(0, 2, size=1024, dtype=np.uint8).tofile(str(DUMMY_BIN))


def _check_samples(arr, label="signal"):
    if len(arr) > MAX_SAMPLES:
        raise ValueError(f"{label} too large: {len(arr)} samples (max {MAX_SAMPLES})")


def _check_file_size(path):
    size = os.path.getsize(path)
    if size > MAX_OUTPUT_BYTES:
        raise ValueError(f"Output file too large: {size} bytes (max {MAX_OUTPUT_BYTES})")


def _save_f32(signal, path):
    _check_samples(signal, "output signal")
    out = np.empty(len(signal) * 2, dtype=np.float32)
    out[0::2] = signal.real.astype(np.float32)
    out[1::2] = signal.imag.astype(np.float32)
    out.tofile(str(path))
    _check_file_size(path)


def _load_f32(path):
    raw = np.fromfile(str(path), dtype=np.float32)
    if len(raw) % 2 != 0:
        raw = raw[:-1]
    signal = raw[0::2] + 1j * raw[1::2]
    _check_samples(signal, "input signal")
    return signal


def process_f32(task_uid):
    out_dir = OUTPUT_DIR / task_uid
    out_dir.mkdir(parents=True, exist_ok=True)
    signal = _load_f32(INPUT_DIR / task_uid / "input.f32")
    _save_f32(send_and_receive(signal), out_dir / "output.f32")


def _process_py_pipeline(task_uid, bits, in_script, out_script):
    out_dir = OUTPUT_DIR / task_uid
    out_dir.mkdir(parents=True, exist_ok=True)

    tx = np.asarray(run_python_function(in_script, "modulate", bits), dtype=np.complex64)
    _check_samples(tx, "modulate() output")
    rx = send_and_receive(tx)
    _save_f32(rx, out_dir / "output.f32")

    decoded = run_python_function(out_script, "demodulate", rx)
    decoded = np.asarray(decoded, dtype=np.uint8)
    _check_samples(decoded, "demodulate() output")
    decoded.tofile(str(out_dir / "output.bin"))
    _check_file_size(out_dir / "output.bin")


def process_py2(task_uid):
    d = INPUT_DIR / task_uid
    bits = np.fromfile(str(DUMMY_BIN), dtype=np.uint8)
    _process_py_pipeline(task_uid, bits, d / "in.py", d / "out.py")


def process_py2bin(task_uid):
    d = INPUT_DIR / task_uid
    bits = np.fromfile(str(d / "input.bin"), dtype=np.uint8)
    _process_py_pipeline(task_uid, bits, d / "in.py", d / "out.py")


def process_combo(task_uid):
    combo = INPUT_DIR / task_uid / "combo.py"
    bits = np.fromfile(str(DUMMY_BIN), dtype=np.uint8)
    _process_py_pipeline(task_uid, bits, combo, combo)


def process_combobin(task_uid):
    d = INPUT_DIR / task_uid
    bits = np.fromfile(str(d / "input.bin"), dtype=np.uint8)
    _process_py_pipeline(task_uid, bits, d / "combo.py", d / "combo.py")


def _process_oct_pipeline(task_uid, bits, in_script, out_script):
    out_dir = OUTPUT_DIR / task_uid
    out_dir.mkdir(parents=True, exist_ok=True)

    tx = np.asarray(run_octave_function(in_script, "modulate", bits.astype(np.float64)), dtype=np.complex64)
    _check_samples(tx, "modulate() output")
    rx = send_and_receive(tx)
    _save_f32(rx, out_dir / "output.f32")

    decoded = run_octave_function(out_script, "demodulate", rx.astype(np.complex128))
    decoded = np.asarray(decoded, dtype=np.uint8)
    _check_samples(decoded, "demodulate() output")
    decoded.tofile(str(out_dir / "output.bin"))
    _check_file_size(out_dir / "output.bin")


def process_oct2(task_uid):
    d = INPUT_DIR / task_uid
    bits = np.fromfile(str(DUMMY_BIN), dtype=np.uint8)
    _process_oct_pipeline(task_uid, bits, d / "in.m", d / "out.m")


def process_oct2bin(task_uid):
    d = INPUT_DIR / task_uid
    bits = np.fromfile(str(d / "input.bin"), dtype=np.uint8)
    _process_oct_pipeline(task_uid, bits, d / "in.m", d / "out.m")


def process_octcombo(task_uid):
    combo = INPUT_DIR / task_uid / "combo.m"
    bits = np.fromfile(str(DUMMY_BIN), dtype=np.uint8)
    _process_oct_pipeline(task_uid, bits, combo, combo)


def process_octcombobin(task_uid):
    d = INPUT_DIR / task_uid
    bits = np.fromfile(str(d / "input.bin"), dtype=np.uint8)
    _process_oct_pipeline(task_uid, bits, d / "combo.m", d / "combo.m")


PROCESSORS = {
    "F32":         process_f32,
    "PY2":         process_py2,
    "PY2BIN":      process_py2bin,
    "COMBO":       process_combo,
    "COMBOBIN":    process_combobin,
    "OCT2":        process_oct2,
    "OCT2BIN":     process_oct2bin,
    "OCTCOMBO":    process_octcombo,
    "OCTCOMBOBIN": process_octcombobin,
}


def poll_and_process():
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.state == "PD").order_by(Task.created_at.asc()).first()
        if not task:
            return False

        task_uid = str(task.uid)
        task.state = "R"
        db.commit()

        try:
            PROCESSORS[task.task_type](task_uid)
            task.state = "D"
            task.done_at = datetime.utcnow()
            db.commit()
        except Exception:
            task.state = "D"
            task.done_at = datetime.utcnow()
            task.error_message = traceback.format_exc()
            db.commit()

        return True
    finally:
        db.close()


def cleanup_old_tasks():
    cutoff = datetime.utcnow() - timedelta(hours=TASK_TTL_HOURS)
    db = SessionLocal()
    try:
        old = db.query(Task).filter(Task.created_at < cutoff).all()
        for task in old:
            uid = str(task.uid)
            for d in (INPUT_DIR / uid, OUTPUT_DIR / uid):
                if d.exists():
                    shutil.rmtree(d)
            db.delete(task)
        if old:
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def main():
    ensure_dummy_bin()
    counter = 0
    while True:
        try:
            had_work = poll_and_process()
        except Exception:
            had_work = False
        if not had_work:
            time.sleep(POLL_INTERVAL)
        counter += 1
        if counter >= 30:
            cleanup_old_tasks()
            counter = 0


if __name__ == "__main__":
    main()
