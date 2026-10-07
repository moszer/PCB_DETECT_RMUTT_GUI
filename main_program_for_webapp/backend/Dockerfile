# RMUTT PCB AOI Station — backend (FastAPI + YOLO). Build context: main_program_for_webapp/
#   docker compose build backend
# TORCH_INDEX picks the PyTorch build: CPU (default, any PC / Mac), cu130 for Jetson JetPack 7.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tesseract-ocr curl \
 && rm -rf /var/lib/apt/lists/*

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --index-url "$TORCH_INDEX" torch torchvision

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/tests ./tests
COPY backend/pytest.ini ./
# The default model and reference sit one level above backend/ (config.REPO_ROOT).
# best.pt is optional: without it, pick/download a model from Hugging Face in Settings.
COPY best.pt* Refs.json /app/

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=6 \
  CMD curl -fs http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "75"]
