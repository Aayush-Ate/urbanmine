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

# Uploads are ephemeral on Render and Fly. Override this if you mount a disk.
ENV UPLOAD_DIR=/tmp/uploads
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
