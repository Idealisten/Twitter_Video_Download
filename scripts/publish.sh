#!/usr/bin/env bash
set -euo pipefail

message="${1:-}"

if [ -z "$message" ]; then
  echo "Usage: ./scripts/publish.sh \"commit message\"" >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Missing git remote 'origin'." >&2
  exit 1
fi

echo "Running local checks..."
python3 -m py_compile app.py
bash -n scripts/deploy.sh
bash -n scripts/publish.sh
docker compose -f compose.yaml config >/dev/null

echo "Staging changes..."
git add -A

if git diff --cached --quiet; then
  echo "No changes to publish."
  exit 0
fi

echo "Committing: ${message}"
git commit -m "$message"

echo "Pushing to origin..."
git push

remote_url="$(git remote get-url origin)"
repo_path="$remote_url"
repo_path="${repo_path#git@github.com:}"
repo_path="${repo_path#https://github.com/}"
repo_path="${repo_path%.git}"

echo
echo "Pushed successfully."
echo "Repository: https://github.com/${repo_path}"
echo "Actions:    https://github.com/${repo_path}/actions"
