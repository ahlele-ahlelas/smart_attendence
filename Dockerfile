FROM python:3.12-slim-bookworm

# System libs needed by opencv (pulled in by deepface)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user, uid 1000 (Hugging Face Spaces convention)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    DEEPFACE_HOME=/home/user/.deepface \
    MPLCONFIGDIR=/home/user/.matplotlib

WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Bake Facenet + RetinaFace weights into the image so cold starts skip the download
RUN python -c "import numpy as np; from deepface import DeepFace; DeepFace.represent(np.zeros((320,320,3), dtype='uint8'), model_name='Facenet', detector_backend='retinaface', enforce_detection=False)"

COPY --chown=user . .

EXPOSE 7860
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
