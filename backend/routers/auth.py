from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from backend.utils import image_to_np, scrub_student
from src.databse.db import (
    check_teacher_exists, create_teacher, teacher_login,
    check_student_exists, create_student, get_student, get_teacher,
    student_login, add_student_face_embeddings,
)
from src.pipelines.face_pipeline import (
    analyze_faces, identify_embedding, find_duplicate_student,
    check_liveness, train_classifier, photo_quality,
)
from src.pipelines.voice_pipeline import get_voice_embedding, voice_available

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str
    password: str


class TeacherRegister(Credentials):
    name: str


@router.post("/teacher/register")
def teacher_register(body: TeacherRegister, request: Request):
    if not body.username.strip() or not body.password or not body.name.strip():
        raise HTTPException(400, "Fill in name, username and password.")
    if check_teacher_exists(body.username.strip()):
        raise HTTPException(409, "Username already taken. Try a different one.")
    teacher = create_teacher(body.username.strip(), body.password, body.name.strip())
    if not teacher:
        raise HTTPException(500, "Could not create the account. Try again.")
    request.session.update(role="teacher", id=teacher["teacher_id"])
    return {"teacher": {"teacher_id": teacher["teacher_id"], "name": teacher["name"]}}


@router.post("/teacher/login")
def teacher_login_route(body: Credentials, request: Request):
    teacher = teacher_login(body.username.strip(), body.password)
    if not teacher:
        raise HTTPException(401, "Wrong username or password.")
    request.session.update(role="teacher", id=teacher["teacher_id"])
    return {"teacher": {"teacher_id": teacher["teacher_id"], "name": teacher["name"]}}


@router.post("/student/login")
def student_password_login(body: Credentials, request: Request):
    student = student_login(body.username.strip(), body.password)
    if not student:
        raise HTTPException(401, "Wrong username or password.")
    request.session.update(role="student", id=student["student_id"])
    return {"student": scrub_student(student)}


@router.post("/student/face-login")
async def student_face_login(request: Request, photo: UploadFile = File(...)):
    img = image_to_np(await photo.read())
    faces = analyze_faces(img)
    if len(faces) == 0:
        raise HTTPException(422, "No face detected. Face the camera in good light and try again.")
    if len(faces) > 1:
        raise HTTPException(422, "More than one face in frame. Make sure only you are visible.")
    if check_liveness(img) is False:
        raise HTTPException(403, "That looks like a photo of a screen or print. Use your live camera.")
    sid, score = identify_embedding(faces[0]["embedding"])
    if sid is None:
        return {"recognized": False}
    student = get_student(sid)
    if not student:
        return {"recognized": False}
    request.session.update(role="student", id=sid)
    return {"recognized": True, "student": scrub_student(student)}


@router.post("/student/register")
async def student_register(
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    photos: list[UploadFile] = File(...),
    audio: Optional[UploadFile] = File(None),
):
    name, username = name.strip(), username.strip()
    if not name or not username or not password:
        raise HTTPException(400, "Fill in name, username and password.")
    if check_student_exists(username):
        raise HTTPException(409, "Username already taken. Try a different one.")

    embeddings, skipped = [], 0
    reasons = set()
    first_img = None
    for up in photos:
        img = image_to_np(await up.read())
        if first_img is None:
            first_img = img
        ok, reason = photo_quality(img)
        if not ok:
            skipped += 1
            reasons.add(reason)
            continue
        faces = analyze_faces(img)
        if len(faces) == 1:
            embeddings.append(faces[0]["embedding"])
        else:
            skipped += 1
            reasons.add("no single clear face")
    if not embeddings:
        detail = "No usable photo"
        if reasons:
            detail += f" ({', '.join(sorted(reasons))})"
        raise HTTPException(422, detail + ". Use sharp, well-lit photos with exactly one face.")

    if first_img is not None and check_liveness(first_img) is False:
        raise HTTPException(403, "That looks like a photo of a screen or print. Use your live camera.")

    # Duplicate-face guard: one face, one account
    dup = find_duplicate_student(embeddings[0])
    if dup is not None:
        existing = get_student(dup)
        who = existing["name"] if existing else "another student"
        raise HTTPException(409, f"This face already belongs to an account ({who}). Use face login instead.")

    voice_emb = None
    if audio is not None and voice_available():
        voice_emb = get_voice_embedding(await audio.read())

    student = create_student(name, username, password,
                             face_embedding=embeddings[0].tolist(),
                             voice_embedding=voice_emb)
    if not student:
        raise HTTPException(500, "Could not save the profile. Try again.")
    if len(embeddings) > 1:
        updated = add_student_face_embeddings(student["student_id"],
                                              [e.tolist() for e in embeddings[1:]])
        student = updated or student
    train_classifier()
    request.session.update(role="student", id=student["student_id"])
    return {"student": scrub_student(student), "photos_used": len(embeddings), "photos_skipped": skipped}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    role, uid = request.session.get("role"), request.session.get("id")
    if role == "student" and uid:
        student = get_student(uid)
        if student:
            return {"role": "student", "student": scrub_student(student)}
    if role == "teacher" and uid:
        teacher = get_teacher(uid)
        if teacher:
            return {"role": "teacher", "teacher": {"teacher_id": teacher["teacher_id"], "name": teacher["name"]}}
    return {"role": None}
