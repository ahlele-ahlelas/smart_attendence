import io
import secrets
from pathlib import Path

import numpy as np
from PIL import Image
from fastapi import HTTPException, Request

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_session_secret():
    """Persisted random secret so sessions survive restarts. Env override wins."""
    import os
    env = os.environ.get("SESSION_SECRET")
    if env:
        return env
    secret_file = PROJECT_ROOT / ".session_secret"
    if secret_file.exists():
        return secret_file.read_text().strip()
    secret = secrets.token_hex(32)
    secret_file.write_text(secret)
    return secret


def image_to_np(data: bytes) -> np.ndarray:
    try:
        return np.array(Image.open(io.BytesIO(data)).convert("RGB"))
    except Exception:
        raise HTTPException(400, "Could not read image file.")


def scrub_student(student: dict) -> dict:
    """Strip secrets/biometrics before sending a student row to the browser."""
    keep = {k: v for k, v in student.items()
            if k not in ("password", "face_embedding", "face_embeddings", "voice_embedding")}
    samples = len(student.get("face_embeddings") or [])
    if student.get("face_embedding"):
        samples += 1
    keep["face_samples"] = samples
    keep["has_voice"] = student.get("voice_embedding") is not None
    return keep


def require_student(request: Request) -> int:
    sess = request.session
    if sess.get("role") != "student" or not sess.get("id"):
        raise HTTPException(401, "Sign in as a student to continue.")
    return sess["id"]


def require_teacher(request: Request) -> int:
    sess = request.session
    if sess.get("role") != "teacher" or not sess.get("id"):
        raise HTTPException(401, "Sign in as a teacher to continue.")
    return sess["id"]
