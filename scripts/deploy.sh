#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/twitter-video-download}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.yaml}"
START_PORT="${HOST_PORT:-}"
MAX_PORT="${MAX_PORT:-65535}"

cd "$APP_DIR"

if [ ! -f "$COMPOSE_FILE" ]; then
  curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/compose.yaml -o "$COMPOSE_FILE"
fi

if [ ! -f "$ENV_FILE" ]; then
  curl -fsSL https://raw.githubusercontent.com/Idealisten/Twitter_Video_Download/main/.env.example -o "$ENV_FILE"
fi

env_port="$(awk -F= '/^HOST_PORT=/{print $2}' "$ENV_FILE" | tail -n 1 | tr -d "\"'[:space:]")"
port="${START_PORT:-${env_port:-8001}}"

port_in_use() {
  local candidate="$1"

  if command -v ss >/dev/null 2>&1; then
    ss -ltn | awk '{print $4}' | grep -Eq "[:.]${candidate}$"
    return $?
  fi

  if command -v netstat >/dev/null 2>&1; then
    netstat -ltn | awk '{print $4}' | grep -Eq "[:.]${candidate}$"
    return $?
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${candidate}" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi

  return 1
}

port_in_use_by_this_service() {
  local candidate="$1"

  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi

  docker ps \
    --filter "name=^/twitter-video-download$" \
    --format '{{.Ports}}' \
    | grep -Eq "(^|[ ,])([^, ]*:)?${candidate}->8000/tcp"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"

  if grep -q "^${key}=" "$ENV_FILE"; then
    awk -v key="$key" -v value="$value" '
      $0 ~ "^" key "=" { print key "=" value; next }
      { print }
    ' "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi

  mv "$tmp" "$ENV_FILE"
}

while [ "$port" -le "$MAX_PORT" ]; do
  if ! port_in_use "$port" || port_in_use_by_this_service "$port"; then
    break
  fi
  echo "Port ${port} is already in use, trying $((port + 1))..."
  port=$((port + 1))
done

if [ "$port" -gt "$MAX_PORT" ]; then
  echo "No available port found between ${START_PORT:-${env_port:-8001}} and ${MAX_PORT}." >&2
  exit 1
fi

set_env_value HOST_PORT "$port"

echo "Using HOST_PORT=${port}"
docker compose -f "$COMPOSE_FILE" pull
docker compose -f "$COMPOSE_FILE" up -d
docker compose -f "$COMPOSE_FILE" ps

echo
echo "Service URL: http://127.0.0.1:${port}"
