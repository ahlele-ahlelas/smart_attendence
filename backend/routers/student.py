from fastapi import APIRouter, Request, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel

from backend.utils import image_to_np, scrub_student, require_student
from src.databse.db import (
    get_student, get_student_subjects, get_student_attendance,
    enroll_student_to_subject, unenroll_student_from_subject,
    is_student_enrolled, get_subject_by_code, get_subject, add_student_face_embeddings,
)
from src.pipelines.face_pipeline import analyze_faces, identify_embedding, train_classifier, check_liveness, photo_quality
from backend import qr_live

router = APIRouter(prefix="/api/student", tags=["student"], dependencies=[Depends(require_student)])


class EnrollBody(BaseModel):
    code: str


class CheckinBody(BaseModel):
    token: str


@router.get("/overview")
def overview(request: Request):
    student_id = request.session["id"]
    student = get_student(student_id)
    if not student:
        raise HTTPException(404, "Account not found.")
    subjects = get_student_subjects(student_id)
    logs = get_student_attendance(student_id)

    stats = {}
    for log in logs:
        sid = log["subject_id"]
        s = stats.setdefault(sid, {"total": 0, "attended": 0})
        s["total"] += 1
        if log.get("is_present"):
            s["attended"] += 1

    out_subjects = []
    for node in subjects:
        sub = node.get("subject") or {}
        sid = sub.get("subject_id")
        s = stats.get(sid, {"total": 0, "attended": 0})
        pct = round(100 * s["attended"] / s["total"]) if s["total"] else None
        out_subjects.append({
            "subject_id": sid,
            "name": sub.get("name"),
            "code": sub.get("subject_code"),
            "section": sub.get("section"),
            "total_classes": s["total"],
            "attended": s["attended"],
            "percent": pct,
        })
    return {"student": scrub_student(student), "subjects": out_subjects}


@router.post("/enroll")
def enroll(body: EnrollBody, request: Request):
    student_id = request.session["id"]
    subject = get_subject_by_code(body.code.strip())
    if not subject:
        raise HTTPException(404, "Subject code not found. Check it and try again.")
    if is_student_enrolled(student_id, subject["subject_id"]):
        return {"already_enrolled": True, "subject": {"name": subject["name"]}}
    enroll_student_to_subject(student_id, subject["subject_id"])
    return {"already_enrolled": False, "subject": {"name": subject["name"]}}


@router.delete("/subjects/{subject_id}")
def unenroll(subject_id: int, request: Request):
    unenroll_student_from_subject(request.session["id"], subject_id)
    return {"ok": True}


@router.get("/report")
def pdf_report(request: Request, period: str = "week"):
    from fastapi.responses import StreamingResponse
    from backend.reports import build_student_report
    student_id = request.session["id"]
    student = get_student(student_id)
    if not student:
        raise HTTPException(404, "Account not found.")
    logs = get_student_attendance(student_id)
    pdf = build_student_report(student, logs, period)
    filename = f"my_attendance_{period}.pdf"
    return StreamingResponse(
        iter([pdf]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/checkin")
def qr_checkin(body: CheckinBody, request: Request):
    """Mark presence in a live QR session (token rotates every 30s)."""
    student_id = request.session["id"]
    session = qr_live.validate_token(body.token)
    if not session:
        raise HTTPException(410, "This QR code has expired. Scan the live code on your teacher's screen.")
    if not is_student_enrolled(student_id, session["subject_id"]):
        raise HTTPException(403, "You're not enrolled in this subject. Join it first, then scan again.")
    student = get_student(student_id)
    qr_live.check_in(body.token, student_id, student["name"])
    subject = get_subject(session["subject_id"])
    return {"subject": subject["name"] if subject else "class"}


@router.post("/face-photos")
async def add_face_photos(request: Request, photos: list[UploadFile] = File(...)):
    student_id = request.session["id"]
    new_embeddings, reasons = [], []
    for up in photos:
        img = image_to_np(await up.read())
        ok, reason = photo_quality(img)
        if not ok:
            reasons.append(reason)
            continue
        faces = analyze_faces(img)
        if len(faces) == 1:
            new_embeddings.append(faces[0]["embedding"].tolist())
        else:
            reasons.append("no single clear face")
    if not new_embeddings:
        detail = "No usable photo"
        if reasons:
            detail += f" ({', '.join(sorted(set(reasons)))})"
        raise HTTPException(422, detail + ". Use sharp, well-lit photos with exactly one face.")
    updated = add_student_face_embeddings(student_id, new_embeddings)
    if not updated:
        raise HTTPException(500, "Could not save photos. Run migrations.sql in Supabase if you haven't yet.")
    train_classifier()
    return {"added": len(new_embeddings), "skipped": len(reasons),
            "skip_reasons": sorted(set(reasons)), "student": scrub_student(updated)}


@router.post("/test-recognition")
async def test_recognition(request: Request, photo: UploadFile = File(...)):
    student_id = request.session["id"]
    img = image_to_np(await photo.read())
    faces = analyze_faces(img)
    if len(faces) == 0:
        return {"result": "no_face"}
    if len(faces) > 1:
        return {"result": "multiple_faces"}
    if check_liveness(img) is False:
        return {"result": "spoof"}
    sid, score = identify_embedding(faces[0]["embedding"])
    return {
        "result": "recognized" if sid == student_id else "not_recognized",
        "matched_someone_else": sid is not None and sid != student_id,
        "score": None if score == float("inf") else round(score, 3),
    }
