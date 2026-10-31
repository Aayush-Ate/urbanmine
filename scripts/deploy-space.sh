#!/usr/bin/env bash
# Deploy backend/ to a Hugging Face Docker Space.
# Usage: scripts/deploy-space.sh <hf-username>/<space-name>
#
# Hugging Face Docker Spaces require a PRO account as of 2026.
# The script uploads a clean copy: no .env, no weights, no uploads, no tests.
set -euo pipefail

REPO_ID="${1:-}"
if [ -z "$REPO_ID" ]; then
  echo "usage: $0 <hf-username>/<space-name>"
  exit 1
fi

cd "$(dirname "$0")/../backend"

if ! hf auth whoami >/dev/null 2>&1; then
  echo "Not logged in. Run: hf auth login"
  exit 1
fi

# Load DATABASE_URL from backend/.env without printing it.
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is empty. Set it in backend/.env first."
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

rsync -a \
  --exclude '.env' \
  --exclude '*.pt' \
  --exclude 'uploads/' \
  --exclude 'data.json' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '*.log' \
  --exclude 'tests/' \
  ./ "$STAGE/"

# A Hugging Face Docker Space refuses to build without a README.md card that
# declares the sdk, so write one into the staged copy. backend/ keeps no README
# of its own any more; the docs live in ../docs.
cat > "$STAGE/README.md" <<'CARD'
---
title: UrbanMine API
sdk: docker
app_port: 7860
short_description: FastAPI and YOLO material detection for UrbanMine
tags:
  - urbanmine
  - fastapi
  - yolo
---

FastAPI backend for UrbanMine. Set DATABASE_URL (the pooled Neon URL) as a Space
secret. UPLOAD_DIR is /tmp/uploads, which is wiped on restart.
CARD

hf repo create "$REPO_ID" --repo-type space --sdk docker --public --exist-ok
hf spaces secrets add "$REPO_ID" -s DATABASE_URL
hf upload "$REPO_ID" "$STAGE" . --repo-type space \
  --commit-message "Deploy UrbanMine backend"

echo "Space: https://huggingface.co/spaces/$REPO_ID"
echo "API:   https://${REPO_ID//\//-}.hf.space"
