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

# Bake the detection weights into the image so cold starts do not download them.
# Two models: yolov8n for everyday objects, YOLOE for the material prompts.
# YOLOE's set_classes() pulls its text encoder (mobileclip_blt.ts, 572MB) into
# the working dir, which is why this runs from /app and why the image grows.
# Failing here is better than silently serving without an open-vocab model.
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt'); \
    from ultralytics import YOLOE; \
    world = YOLOE('yoloe-11s-seg.pt'); world.set_classes(['brick']); \
    print('detection weights ok')"

# Bake CLIP into the image too. The cache path is fixed so runtime can find it.
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "from transformers import CLIPModel, CLIPProcessor; \
    CLIPModel.from_pretrained('openai/clip-vit-base-patch32'); \
    CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32')"

COPY . .

# Uploads are ephemeral on Vercel, Spaces, Render, and Fly.
ENV UPLOAD_DIR=/tmp/uploads

# Vercel and Spaces route to the port in PORT. Local default is 7860.
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
