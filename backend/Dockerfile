FROM python:3.11-slim

WORKDIR /app

# OpenCV (pulled by ultralytics) needs these two system libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install CPU torch first. Without this, pip pulls the huge CUDA build.
RUN pip install --no-cache-dir torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Uploads are ephemeral on Spaces, Render, and Fly. Use object storage for real use.
ENV UPLOAD_DIR=/tmp/uploads

# Hugging Face Spaces routes to 7860. Render sets PORT (10000 by default).
EXPOSE 7860
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
