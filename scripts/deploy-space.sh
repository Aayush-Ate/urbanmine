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

hf repo create "$REPO_ID" --repo-type space --sdk docker --public --exist-ok
hf spaces secrets add "$REPO_ID" -s DATABASE_URL
hf upload "$REPO_ID" "$STAGE" . --repo-type space \
  --commit-message "Deploy UrbanMine backend"

echo "Space: https://huggingface.co/spaces/$REPO_ID"
echo "API:   https://${REPO_ID//\//-}.hf.space"
