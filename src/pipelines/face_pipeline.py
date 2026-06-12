import cv2
import numpy as np
from deepface import DeepFace
from sklearn.svm import SVC
from src.databse.db import get_all_students

# Normalised Euclidean distance: same person ~<0.7, different person ~>1.0
RESEMBLANCE_THRESHOLD = 0.9
# Stricter cut for "this face already belongs to an account" (duplicate guard)
DUPLICATE_THRESHOLD = 0.65

_MODEL_CACHE = {"data": None, "fresh": False}


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / (np.linalg.norm(v) + 1e-10)


def analyze_faces(image_np):
    """Detect every face: returns list of {embedding: np.array, box: {x,y,w,h}}."""
    try:
        results = DeepFace.represent(
            image_np,
            model_name="Facenet",
            enforce_detection=False,
            detector_backend="retinaface"
        )
    except Exception:
        return []
    faces = []
    for r in results:
        # enforce_detection=False returns the whole frame as a confidence-0
        # "face" when nothing was detected; drop those so "no face" is real
        conf = r.get("face_confidence")
        if conf is not None and conf <= 0:
            continue
        area = r.get("facial_area") or {}
        faces.append({
            "embedding": np.array(r["embedding"]),
            "box": {k: int(area.get(k) or 0) for k in ("x", "y", "w", "h")},
        })
    return faces


def photo_quality(image_np):
    """Cheap CV gate before embedding: reject photos that would poison the
    profile. Returns (ok, reason) where reason is None or 'too dark'/'blurry'."""
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    if gray.mean() < 40:
        return False, "too dark"
    if cv2.Laplacian(gray, cv2.CV_64F).var() < 40:
        return False, "blurry"
    return True, None


def check_liveness(image_np):
    """Anti-spoofing: True=real face, False=spoof (photo of a photo), None=unknown."""
    try:
        faces = DeepFace.extract_faces(
            image_np,
            detector_backend="retinaface",
            enforce_detection=False,
            anti_spoofing=True
        )
        if not faces:
            return None
        return all(f.get("is_real", True) for f in faces)
    except Exception:
        return None


def get_trained_model():
    if _MODEL_CACHE["fresh"]:
        return _MODEL_CACHE["data"]
    X, y = [], []
    student_db = get_all_students()
    if not student_db:
        return None
    for student in student_db:
        embeddings = []
        primary = student.get("face_embedding")
        if primary:
            embeddings.append(primary)
        embeddings.extend(student.get("face_embeddings") or [])
        for embedding in embeddings:
            X.append(_unit(embedding).tolist())
            y.append(student["student_id"])
    if len(X) == 0:
        return 0
    clf = SVC(kernel='linear', probability=True, class_weight='balanced')
    try:
        clf.fit(X, y)
    except ValueError:
        pass
    data = {'clf': clf, 'X': X, 'y': y}
    _MODEL_CACHE.update(data=data, fresh=True)
    return data


def train_classifier():
    #invalidate cache so next call retrains on fresh DB state
    _MODEL_CACHE.update(data=None, fresh=False)
    return bool(get_trained_model())


def identify_embedding(embedding, model_data=None):
    """Match one embedding against enrolled students.
    Returns (student_id, score) or (None, score) when no one is close enough."""
    model_data = model_data or get_trained_model()
    if not model_data:
        return None, float("inf")
    clf, X_train, y_train = model_data['clf'], model_data['X'], model_data['y']
    all_students = sorted(set(y_train))
    norm_enc = _unit(embedding)
    if len(all_students) >= 2:
        predicted_id = clf.predict([norm_enc])[0]
    else:
        predicted_id = all_students[0]
    # X_train is unit-normalised; best of all of the student's enrolled photos
    sample_idxs = [i for i, sid in enumerate(y_train) if sid == predicted_id]
    score = min(np.linalg.norm(np.array(X_train[i]) - norm_enc) for i in sample_idxs)
    if score <= RESEMBLANCE_THRESHOLD:
        return int(predicted_id), float(score)
    return None, float(score)


def find_duplicate_student(embedding):
    """Duplicate-face guard at registration: student_id if this face already
    matches an existing account closely, else None."""
    sid, score = identify_embedding(embedding)
    return sid if sid is not None and score <= DUPLICATE_THRESHOLD else None


def analyze_class_photo(image_np):
    """Class-photo review: every face with its box and who it matched.
    Returns {'faces': [{'box', 'student_id', 'score'}], 'num_faces': int}."""
    model_data = get_trained_model()
    faces_out = []
    for face in analyze_faces(image_np):
        sid, score = (None, float("inf"))
        if model_data:
            sid, score = identify_embedding(face["embedding"], model_data)
        faces_out.append({"box": face["box"], "student_id": sid,
                          "score": None if score == float("inf") else round(score, 3)})
    return {"faces": faces_out, "num_faces": len(faces_out)}
