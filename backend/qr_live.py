"""Live QR attendance sessions.

A teacher starts a session; the dashboard shows a QR whose token rotates
every TOKEN_WINDOW seconds (HMAC over the time window, so a screenshot
goes stale almost immediately). Students scan, sign in, and check in.
State is in-memory: a live session only matters while the teacher's
modal is open.
"""
import hashlib
import hmac
import secrets
import time

TOKEN_WINDOW = 30          # seconds a single QR code stays valid
SESSION_TTL = 60 * 60      # drop abandoned sessions after an hour

_sessions: dict[str, dict] = {}


def _purge():
    now = time.time()
    for qid in [q for q, s in _sessions.items() if now - s["created"] > SESSION_TTL]:
        _sessions.pop(qid, None)


def start_session(subject_id: int, teacher_id: int) -> str:
    _purge()
    qid = secrets.token_urlsafe(8)
    _sessions[qid] = {
        "subject_id": subject_id,
        "teacher_id": teacher_id,
        "secret": secrets.token_bytes(32),
        "checked_in": {},          # student_id -> {"name", "time"}
        "created": time.time(),
    }
    return qid


def get_session(qid: str, teacher_id: int | None = None):
    session = _sessions.get(qid)
    if not session:
        return None
    if teacher_id is not None and session["teacher_id"] != teacher_id:
        return None
    return session


def end_session(qid: str):
    _sessions.pop(qid, None)


def _sign(secret: bytes, window: int) -> str:
    return hmac.new(secret, str(window).encode(), hashlib.sha256).hexdigest()[:12]


def current_token(qid: str) -> str:
    session = _sessions[qid]
    window = int(time.time() // TOKEN_WINDOW)
    return f"{qid}.{window}.{_sign(session['secret'], window)}"


def validate_token(token: str):
    """Returns the session dict, or None. Accepts the current and the
    previous window so a code scanned right at rotation still works."""
    try:
        qid, window_str, sig = token.split(".")
        window = int(window_str)
    except ValueError:
        return None
    session = _sessions.get(qid)
    if not session:
        return None
    now_window = int(time.time() // TOKEN_WINDOW)
    if window not in (now_window, now_window - 1):
        return None
    if not hmac.compare_digest(_sign(session["secret"], window), sig):
        return None
    return session


def check_in(token: str, student_id: int, name: str):
    session = validate_token(token)
    if not session:
        return None
    session["checked_in"][student_id] = {"name": name, "time": time.strftime("%H:%M:%S")}
    return session
