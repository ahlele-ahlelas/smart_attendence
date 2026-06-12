from src.databse.config import supabase
import bcrypt

def hash_pass(password):
    #hash password using bcrypt
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def check_pass(password, hashed):
    #check if password matches hashed password
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def check_teacher_exists(username):
    #check for unique username, return false if username already exists
    response = supabase.table("teachers").select("username").eq("username", username).execute()
    return len(response.data) > 0

def create_teacher(username, password,name):
    #create teacher account, return true if successful
    data = {
        "username": username,
        "password": hash_pass(password),
        "name": name
    }
    response = supabase.table("teachers").insert(data).execute()
    return response.data[0] if response.data else None

def teacher_login(username, password):
    #check if username exists and password is correct, return teacher data if successful
    response = supabase.table("teachers").select("*").eq("username", username).execute()
    if response.data:
        teacher = response.data[0]
        if check_pass(password, teacher["password"]):
            return teacher
    return None

def get_all_students():
    response = supabase.table("students").select("*").execute()
    return response.data

def check_student_exists(username):
    response = supabase.table("students").select("username").eq("username", username).execute()
    return len(response.data) > 0

def create_student(name, username, password, face_embedding=None, voice_embedding=None):
    data = {
        "name": name,
        "username": username,
        "password": hash_pass(password),
        "face_embedding": face_embedding,
        "voice_embedding": voice_embedding
    }
    response = supabase.table("students").insert(data).execute()
    return response.data[0] if response.data else None


def add_student_face_embeddings(student_id, new_embeddings):
    #append extra face embeddings (list of 128-d vectors) to a student's profile, return updated row
    response = supabase.table("students").select("face_embeddings").eq("student_id", student_id).execute()
    existing = response.data[0].get("face_embeddings") if response.data else None
    combined = (existing or []) + new_embeddings
    updated = supabase.table("students").update({"face_embeddings": combined}).eq("student_id", student_id).execute()
    return updated.data[0] if updated.data else None


def create_subject(subject_name, subject_code, subject_section, teacher_id):
    data = {
        "name": subject_name,
        "subject_code": subject_code,
        "section": subject_section,
        "teacher_id": teacher_id
    }
    response = supabase.table("subject").insert(data).execute()
    return response.data[0] if response.data else None

def get_teacher_subjects(teacher_id):
    response = supabase.table("subject").select("*, subject_students(count), attendance_logs(timestamp)").eq("teacher_id", teacher_id).execute()
    subjects = response.data if response.data else []
    for subject in subjects:
        subject['total_students'] = subject.get('subject_students', [{}])[0].get('count', 0) if subject.get('subject_students') else 0
        attendence = subject.get('attendance_logs', [])
        subject['total_classes'] = len(set(log['timestamp'] for log in attendence)) if attendence else 0
        subject.pop('subject_students', None)
        subject.pop('attendance_logs', None)
    return subjects

def enroll_student_to_subject(student_id, subject_id):
    data = {
        "student_id": student_id,
        "subject_id": subject_id
    }
    response = supabase.table("subject_students").insert(data).execute()
    return response.data[0] if response.data else None

def unenroll_student_from_subject(student_id, subject_id):
    response = supabase.table("subject_students").delete().eq("student_id", student_id).eq("subject_id", subject_id).execute()
    return response.data[0] if response.data else None

def get_student_subjects(student_id):
    response = supabase.table("subject_students").select("*,subject(*)").eq("student_id", student_id).execute()
    return response.data if response.data else []

def get_student_attendance(student_id):
    response = supabase.table("attendance_logs").select("*,subject(*)").eq("student_id", student_id).execute()
    return response.data if response.data else []

def create_attendance(logs):
    response = supabase.table("attendance_logs").insert(logs).execute()
    return response.data if response.data else None

def student_login(username, password):
    #password fallback login for students
    response = supabase.table("students").select("*").eq("username", username).execute()
    if response.data:
        student = response.data[0]
        if student.get("password") and check_pass(password, student["password"]):
            return student
    return None

def get_student(student_id):
    response = supabase.table("students").select("*").eq("student_id", student_id).execute()
    return response.data[0] if response.data else None

def get_teacher(teacher_id):
    response = supabase.table("teachers").select("*").eq("teacher_id", teacher_id).execute()
    return response.data[0] if response.data else None

def get_subject(subject_id):
    response = supabase.table("subject").select("*").eq("subject_id", subject_id).execute()
    return response.data[0] if response.data else None

def get_subject_by_code(subject_code):
    response = supabase.table("subject").select("*").eq("subject_code", subject_code).execute()
    return response.data[0] if response.data else None

def get_enrolled_students(subject_id):
    #roster with full student rows
    response = supabase.table("subject_students").select("*,students(*)").eq("subject_id", subject_id).execute()
    return [node["students"] for node in (response.data or []) if node.get("students")]

def is_student_enrolled(student_id, subject_id):
    response = supabase.table("subject_students").select("student_id").eq("student_id", student_id).eq("subject_id", subject_id).execute()
    return len(response.data) > 0

def create_class_session(subject_id, label=None):
    #one row per attendance-taking; returns None gracefully when migration not applied yet
    try:
        response = supabase.table("class_sessions").insert({"subject_id": subject_id, "label": label}).execute()
        return response.data[0] if response.data else None
    except Exception:
        return None

def get_attendance_for_subject(subject_id):
    response = supabase.table("attendance_logs").select("*").eq("subject_id", subject_id).execute()
    return response.data if response.data else []