FROM python:3.11-slim

# opencv/insightface/onnxruntime need these system libs to import at all
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download models at BUILD time so the first request doesn't pay for a
# slow (or, on a network-restricted host, failing) download.
RUN python -m spacy download en_core_web_lg
RUN python - <<'PY'
from sentence_transformers import SentenceTransformer
from transformers import DistilBertModel, DistilBertTokenizerFast
import insightface

SentenceTransformer("all-MiniLM-L6-v2")
DistilBertTokenizerFast.from_pretrained("distilbert-base-uncased")
DistilBertModel.from_pretrained("distilbert-base-uncased")
# Pulls the buffalo_l detection/recognition model pack into the image so
# face_recognition/image_utils.py's module-level FaceAnalysis().prepare()
# doesn't try to download it on first container start.
insightface.app.FaceAnalysis(providers=["CPUExecutionProvider"]).prepare(ctx_id=0, det_size=(640, 640))
PY

COPY app ./app

# app/model_output_v3 (fine-tuned sentiment DistilBERT checkpoint, ~254MB) is
# gitignored — too large for the git repo — so it isn't copied in above. The
# app downloads it from Hugging Face Hub on the first /sentiment request
# instead (see app/sentiment_analysis/routes.py's _download_from_hf), as
# long as HF_MODEL_REPO is set as a runtime environment variable. Upload the
# checkpoint once with scripts/upload_model_to_hf.py.

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
