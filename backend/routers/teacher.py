import csv
import io
import time
from datetime import datetime
from typing import Optional

import segno
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend import qr_live
from backend.utils import image_to_np, require_teacher
from src.databse.db import (
    get_teacher_subjects, create_subject, get_subject,
    get_enrolled_students, get_attendance_for_subject,
    create_class_session, create_attendance,
)
from src.pipelines.face_pipeline import analyze_class_photo
from src.pipelines.voice_pipeline import process_bulk_audio, voice_available

router = APIRouter(prefix="/api/teacher", tags=["teacher"], dependencies=[Depends(require_teacher)])

LOW_ATTENDANCE_CUTOFF = 75


def _own_subject(request: Request, subject_id: int) -> dict:
    subject = get_subject(subject_id)
    if not subject or subject.get("teacher_id") != request.session["id"]:
        raise HTTPException(404, "Subject not found.")
    return subject


def _student_stats(subject_id: int) -> dict:
    """student_id -> {attended, total, percent} for one subject."""
    stats = {}
    for log in get_attendance_for_subject(subject_id):
        s = stats.setdefault(log["student_id"], {"attended": 0, "total": 0})
        s["total"] += 1
        if log.get("is_present"):
            s["attended"] += 1
    for s in stats.values():
        s["percent"] = round(100 * s["attended"] / s["total"]) if s["total"] else None
    return stats


def _sessions(subject_id: int) -> list:
    """Attendance grouped into sessions (session_id when migrated, else timestamp)."""
    groups = {}
    for log in get_attendance_for_subject(subject_id):
        key = f"s{log['session_id']}" if log.get("session_id") else f"t{log.get('timestamp')}"
        g = groups.setdefault(key, {"key": key, "time": log.get("timestamp"), "present": 0, "total": 0})
        g["total"] += 1
        if log.get("is_present"):
            g["present"] += 1
    return sorted(groups.values(), key=lambda g: g["time"] or "", reverse=True)


class SubjectBody(BaseModel):
    name: str
    code: str
    section: str


class ConfirmEntry(BaseModel):
    student_id: int
    is_present: bool


class ConfirmBody(BaseModel):
    subject_id: int
    entries: list[ConfirmEntry]


class QrStartBody(BaseModel):
    subject_id: int


class QrBody(BaseModel):
    qid: str


@router.get("/overview")
def overview(request: Request):
    subjects = get_teacher_subjects(request.session["id"])
    for sub in subjects:
        stats = _student_stats(sub["subject_id"])
        sub["low_attendance"] = sum(
            1 for s in stats.values()
            if s["percent"] is not None and s["percent"] < LOW_ATTENDANCE_CUTOFF
        )
    return {"subjects": subjects}


@router.post("/subjects")
def add_subject(body: SubjectBody, request: Request):
    if not body.name.strip() or not body.code.strip() or not body.section.strip():
        raise HTTPException(400, "Fill in name, code and section.")
    subject = create_subject(body.name.strip(), body.code.strip(), body.section.strip(), request.session["id"])
    if not subject:
        raise HTTPException(500, "Could not create the subject.")
    return {"subject": subject}


@router.get("/subjects/{subject_id}/share")
def share_subject(subject_id: int, request: Request):
    subject = _own_subject(request, subject_id)
    join_url = f"{request.base_url}student.html?join-code={subject['subject_code']}"
    qr = segno.make(join_url)
    return {
        "join_url": join_url,
        "code": subject["subject_code"],
        "qr": qr.png_data_uri(scale=8, border=1),
    }


@router.get("/subjects/{subject_id}/roster")
def roster(subject_id: int, request: Request):
    _own_subject(request, subject_id)
    stats = _student_stats(subject_id)
    out = []
    for student in get_enrolled_students(subject_id):
        s = stats.get(student["student_id"], {"attended": 0, "total": 0, "percent": None})
        out.append({
            "student_id": student["student_id"],
            "name": student["name"],
            "username": student.get("username"),
            "attended": s["attended"],
            "total": s["total"],
            "percent": s["percent"],
            "low": s["percent"] is not None and s["percent"] < LOW_ATTENDANCE_CUTOFF,
            "has_voice": student.get("voice_embedding") is not None,
        })
    out.sort(key=lambda r: (r["name"] or "").lower())
    return {"students": out}


@router.post("/attendance/analyze")
async def analyze_attendance(request: Request,
                             subject_id: int = Form(...),
                             photos: list[UploadFile] = File(...)):
    _own_subject(request, subject_id)
    students = get_enrolled_students(subject_id)
    if not students:
        raise HTTPException(422, "No students enrolled in this subject yet.")
    names = {s["student_id"]: s["name"] for s in students}

    detected_sources: dict[int, list[str]] = {}
    photo_results = []
    for idx, up in enumerate(photos):
        img = image_to_np(await up.read())
        result = analyze_class_photo(img)
        faces = []
        for face in result["faces"]:
            sid = face["student_id"]
            enrolled_here = sid in names
            if enrolled_here:
                detected_sources.setdefault(sid, []).append(f"Photo {idx + 1}")
            faces.append({
                "box": face["box"],
                "student_id": sid if enrolled_here else None,
                "name": names.get(sid) if enrolled_here else None,
                "score": face["score"],
            })
        photo_results.append({"photo": idx, "num_faces": result["num_faces"], "faces": faces})

    proposal = [{
        "student_id": s["student_id"],
        "name": s["name"],
        "is_present": s["student_id"] in detected_sources,
        "sources": detected_sources.get(s["student_id"], []),
    } for s in sorted(students, key=lambda x: (x["name"] or "").lower())]

    return {"photos": photo_results, "proposal": proposal}


@router.post("/attendance/voice")
async def voice_attendance(request: Request,
                           subject_id: int = Form(...),
                           audio: UploadFile = File(...)):
    _own_subject(request, subject_id)
    if not voice_available():
        raise HTTPException(503, "Voice recognition isn't installed on this server (resemblyzer/librosa).")
    students = get_enrolled_students(subject_id)
    if not students:
        raise HTTPException(422, "No students enrolled in this subject yet.")
    candidates = {s["student_id"]: s["voice_embedding"]
                  for s in students if s.get("voice_embedding") is not None}
    if not candidates:
        raise HTTPException(422, "No enrolled students have voice samples yet.")
    scores = process_bulk_audio(await audio.read(), candidates)
    proposal = [{
        "student_id": s["student_id"],
        "name": s["name"],
        "is_present": int(s["student_id"]) in scores or s["student_id"] in scores,
        "sources": [f"voice {scores.get(s['student_id'], scores.get(int(s['student_id']), 0)):.2f}"]
                   if (s["student_id"] in scores or int(s["student_id"]) in scores) else [],
    } for s in sorted(students, key=lambda x: (x["name"] or "").lower())]
    return {"proposal": proposal}


@router.post("/attendance/confirm")
def confirm_attendance(body: ConfirmBody, request: Request):
    subject = _own_subject(request, body.subject_id)
    if not body.entries:
        raise HTTPException(400, "Nothing to save.")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session = create_class_session(body.subject_id, label=f"{subject['name']} {timestamp}")
    logs = [{
        "student_id": e.student_id,
        "subject_id": body.subject_id,
        "timestamp": timestamp,
        "is_present": e.is_present,
    } for e in body.entries]
    if session:
        for log in logs:
            log["session_id"] = session["session_id"]
    try:
        saved = create_attendance(logs)
    except Exception:
        # session_id column missing (migration not run): save without it
        for log in logs:
            log.pop("session_id", None)
        saved = create_attendance(logs)
    if not saved:
        raise HTTPException(500, "Could not save attendance.")
    present = sum(1 for e in body.entries if e.is_present)
    return {"saved": len(saved), "present": present, "total": len(body.entries)}


@router.get("/records")
def records(request: Request, subject_id: int, date: Optional[str] = None):
    _own_subject(request, subject_id)
    sessions = _sessions(subject_id)
    if date:
        sessions = [s for s in sessions if (s["time"] or "").startswith(date)]
    return {"sessions": sessions}


@router.get("/records/detail")
def record_detail(request: Request, subject_id: int, key: str):
    _own_subject(request, subject_id)
    students = {s["student_id"]: s["name"] for s in get_enrolled_students(subject_id)}
    rows = []
    for log in get_attendance_for_subject(subject_id):
        log_key = f"s{log['session_id']}" if log.get("session_id") else f"t{log.get('timestamp')}"
        if log_key != key:
            continue
        rows.append({
            "student_id": log["student_id"],
            "name": students.get(log["student_id"], f"Student {log['student_id']}"),
            "is_present": bool(log.get("is_present")),
        })
    rows.sort(key=lambda r: (r["name"] or "").lower())
    return {"rows": rows}


@router.get("/export")
def export_csv(request: Request, subject_id: int):
    subject = _own_subject(request, subject_id)
    students = get_enrolled_students(subject_id)
    logs = get_attendance_for_subject(subject_id)

    sessions = {}
    presence = {}
    for log in logs:
        key = f"s{log['session_id']}" if log.get("session_id") else f"t{log.get('timestamp')}"
        sessions.setdefault(key, log.get("timestamp") or "")
        presence[(log["student_id"], key)] = bool(log.get("is_present"))
    ordered = sorted(sessions.items(), key=lambda kv: kv[1])

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Student", "Username"] + [t for _, t in ordered] + ["Attended", "Total", "Percent"])
    for s in sorted(students, key=lambda x: (x["name"] or "").lower()):
        cells, attended, total = [], 0, 0
        for key, _ in ordered:
            mark = presence.get((s["student_id"], key))
            if mark is None:
                cells.append("")
            else:
                total += 1
                attended += int(mark)
                cells.append("P" if mark else "A")
        pct = f"{round(100 * attended / total)}%" if total else ""
        writer.writerow([s["name"], s.get("username", "")] + cells + [attended, total, pct])

    filename = f"attendance_{subject['subject_code']}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/qr/start")
def qr_start(body: QrStartBody, request: Request):
    _own_subject(request, body.subject_id)
    if not get_enrolled_students(body.subject_id):
        raise HTTPException(422, "No students enrolled in this subject yet.")
    qid = qr_live.start_session(body.subject_id, request.session["id"])
    return {"qid": qid, "window": qr_live.TOKEN_WINDOW}


@router.get("/qr/code")
def qr_code(request: Request, qid: str):
    session = qr_live.get_session(qid, request.session["id"])
    if not session:
        raise HTTPException(404, "QR session not found (it may have expired).")
    token = qr_live.current_token(qid)
    url = f"{request.base_url}attend?t={token}"
    qr = segno.make(url)
    expires_in = qr_live.TOKEN_WINDOW - int(time.time() % qr_live.TOKEN_WINDOW)
    return {"qr": qr.png_data_uri(scale=7, border=1), "expires_in": expires_in}


@router.get("/qr/status")
def qr_status(request: Request, qid: str):
    session = qr_live.get_session(qid, request.session["id"])
    if not session:
        raise HTTPException(404, "QR session not found (it may have expired).")
    feed = [{"student_id": sid, **info} for sid, info in session["checked_in"].items()]
    feed.sort(key=lambda f: f["time"])
    return {"checked_in": feed}


@router.post("/qr/finish")
def qr_finish(body: QrBody, request: Request):
    session = qr_live.get_session(body.qid, request.session["id"])
    if not session:
        raise HTTPException(404, "QR session not found (it may have expired).")
    students = get_enrolled_students(session["subject_id"])
    proposal = [{
        "student_id": s["student_id"],
        "name": s["name"],
        "is_present": s["student_id"] in session["checked_in"],
        "sources": [f"QR {session['checked_in'][s['student_id']]['time']}"]
                   if s["student_id"] in session["checked_in"] else [],
    } for s in sorted(students, key=lambda x: (x["name"] or "").lower())]
    qr_live.end_session(body.qid)
    return {"subject_id": session["subject_id"], "proposal": proposal}


@router.post("/qr/cancel")
def qr_cancel(body: QrBody, request: Request):
    session = qr_live.get_session(body.qid, request.session["id"])
    if session:
        qr_live.end_session(body.qid)
    return {"ok": True}


@router.get("/report")
def pdf_report(request: Request, subject_id: int, period: str = "week"):
    from backend.reports import build_teacher_report
    subject = _own_subject(request, subject_id)
    roster = get_enrolled_students(subject_id)
    logs = get_attendance_for_subject(subject_id)
    pdf = build_teacher_report(subject, roster, logs, period)
    filename = f"report_{subject['subject_code']}_{period}.pdf"
    return StreamingResponse(
        iter([pdf]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _smart_insights(logs, names):
    """Pattern detection over the attendance history: consecutive-absence
    streaks, sharp declines, and weekday absence clusters."""
    from datetime import datetime as dt

    # Ordered session history per student: [(session_time, is_present)]
    sessions = {}
    for log in logs:
        key = f"s{log['session_id']}" if log.get("session_id") else f"t{log.get('timestamp')}"
        sessions.setdefault(key, {"time": log.get("timestamp"), "marks": {}})
        sessions[key]["marks"][log["student_id"]] = bool(log.get("is_present"))
    ordered = sorted(sessions.values(), key=lambda s: s["time"] or "")

    insights = []

    # 1. Trailing absence streaks (>= 3 classes in a row)
    streaks = []
    for sid, name in names.items():
        history = [s["marks"][sid] for s in ordered if sid in s["marks"]]
        streak = 0
        for mark in reversed(history):
            if mark:
                break
            streak += 1
        if streak >= 3:
            streaks.append((streak, name))
    for streak, name in sorted(streaks, reverse=True)[:3]:
        insights.append({"icon": "🚨", "text": f"{name} has missed the last {streak} classes in a row."})

    # 2. Sharp declines: last 3 sessions vs everything before
    for sid, name in names.items():
        history = [s["marks"][sid] for s in ordered if sid in s["marks"]]
        if len(history) >= 6:
            prior, recent = history[:-3], history[-3:]
            prior_rate = 100 * sum(prior) / len(prior)
            recent_rate = 100 * sum(recent) / len(recent)
            if prior_rate - recent_rate >= 40:
                insights.append({"icon": "📉", "text":
                    f"{name}'s attendance dropped from {round(prior_rate)}% to {round(recent_rate)}% over the last 3 classes."})

    # 3. Weekday pattern: which day collects the most absences
    day_stats = {}
    for s in ordered:
        try:
            day = dt.fromisoformat(str(s["time"]).replace(" ", "T")).strftime("%A")
        except (ValueError, TypeError):
            continue
        d = day_stats.setdefault(day, {"absent": 0, "total": 0})
        d["absent"] += sum(1 for present in s["marks"].values() if not present)
        d["total"] += len(s["marks"])
    if len(day_stats) >= 2 and sum(d["total"] for d in day_stats.values()) >= 24:
        rates = {day: 100 * d["absent"] / d["total"] for day, d in day_stats.items() if d["total"]}
        avg = sum(rates.values()) / len(rates)
        worst_day, worst_rate = max(rates.items(), key=lambda kv: kv[1])
        if worst_rate >= avg + 15:
            insights.append({"icon": "📅", "text":
                f"Most absences happen on {worst_day}s ({round(worst_rate)}% absent vs {round(avg)}% average)."})

    return insights[:6]


@router.get("/analytics")
def analytics(request: Request, subject_id: int):
    _own_subject(request, subject_id)
    stats = _student_stats(subject_id)
    students = get_enrolled_students(subject_id)
    rows = []
    for s in students:
        st = stats.get(s["student_id"], {"attended": 0, "total": 0, "percent": None})
        rows.append({"student_id": s["student_id"], "name": s["name"], **st})
    rows.sort(key=lambda r: (r["percent"] if r["percent"] is not None else 101))
    chronic = [r for r in rows if r["percent"] is not None and r["percent"] < LOW_ATTENDANCE_CUTOFF]
    trend = list(reversed(_sessions(subject_id)))  # oldest -> newest for charts
    logs = get_attendance_for_subject(subject_id)
    names = {s["student_id"]: s["name"] for s in students}
    return {"students": rows, "chronic": chronic, "trend": trend,
            "cutoff": LOW_ATTENDANCE_CUTOFF,
            "insights": _smart_insights(logs, names)}
