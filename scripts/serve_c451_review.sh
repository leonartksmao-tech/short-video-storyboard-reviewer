#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_PROJECT_DIR="$REPO_ROOT/0527_work"
EXAMPLE_PROJECT_DIR="$REPO_ROOT/examples"
if [[ -n "${SHORT_VIDEO_REVIEW_PROJECT_DIR:-}" ]]; then
  PROJECT_DIR="$SHORT_VIDEO_REVIEW_PROJECT_DIR"
elif [[ -f "$DEFAULT_PROJECT_DIR/c451_tool_output/storyboard_preview.html" ]]; then
  PROJECT_DIR="$DEFAULT_PROJECT_DIR"
elif [[ -f "$EXAMPLE_PROJECT_DIR/c451_tool_output/storyboard_preview.html" ]]; then
  PROJECT_DIR="$EXAMPLE_PROJECT_DIR"
else
  PROJECT_DIR="$DEFAULT_PROJECT_DIR"
fi
PORT="${SHORT_VIDEO_REVIEW_PORT:-8765}"
LOG_DIR="$REPO_ROOT/.short_video_review"
LOG_FILE="$LOG_DIR/server.log"
PID_FILE="$LOG_DIR/server.pid"
PREVIEW_PATH="$PROJECT_DIR/c451_tool_output/storyboard_preview.html"

detect_lan_ip() {
  local iface ip
  for iface in en0 en1 en2 en3; do
    ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    if [[ -n "$ip" ]]; then
      printf "%s" "$ip"
      return
    fi
  done
  printf "127.0.0.1"
}

port_in_use() {
  lsof -ti "tcp:$1" >/dev/null 2>&1
}

server_is_healthy() {
  local url="$1"
  curl -fsS --max-time 1 "$url" >/dev/null 2>&1
}

wait_for_server() {
  local url="$1"
  local attempt
  for attempt in {1..20}; do
    if server_is_healthy "$url"; then
      return 0
    fi
    sleep 0.15
  done
  return 1
}

if [[ ! -f "$PREVIEW_PATH" ]]; then
  osascript -e "display dialog \"找不到审片页面：$PREVIEW_PATH\" buttons {\"好\"} default button \"好\"" >/dev/null 2>&1 || true
  echo "Missing preview: $PREVIEW_PATH" >&2
  exit 1
fi

LAN_IP="$(detect_lan_ip)"
LOCAL_URL="http://127.0.0.1:$PORT/c451_tool_output/storyboard_preview.html"
LAN_URL="http://$LAN_IP:$PORT/c451_tool_output/storyboard_preview.html"

SERVER_PID=""
START_SERVER=1
if port_in_use "$PORT" && server_is_healthy "$LOCAL_URL"; then
  START_SERVER=0
else
  while port_in_use "$PORT"; do
    PORT=$((PORT + 1))
  done
  LOCAL_URL="http://127.0.0.1:$PORT/c451_tool_output/storyboard_preview.html"
  LAN_URL="http://$LAN_IP:$PORT/c451_tool_output/storyboard_preview.html"
fi

if [[ "${SHORT_VIDEO_REVIEW_DRY_RUN:-0}" == "1" ]]; then
  printf "PROJECT_DIR=%s\n" "$PROJECT_DIR"
  printf "LOCAL_URL=%s\n" "$LOCAL_URL"
  printf "LAN_URL=%s\n" "$LAN_URL"
  exit 0
fi

mkdir -p "$LOG_DIR"
if [[ "$START_SERVER" == "1" ]]; then
  python3 -m http.server "$PORT" --bind 0.0.0.0 --directory "$PROJECT_DIR" > "$LOG_FILE" 2>&1 &
  SERVER_PID="$!"
  echo "$SERVER_PID" > "$PID_FILE"

  if ! wait_for_server "$LOCAL_URL"; then
    osascript -e "display dialog \"审片服务启动失败，请查看：$LOG_FILE\" buttons {\"好\"} default button \"好\"" >/dev/null 2>&1 || true
    echo "Review server failed to start. Log: $LOG_FILE" >&2
    exit 1
  fi
fi

printf "%s" "$LAN_URL" | pbcopy

if [[ "${SHORT_VIDEO_REVIEW_NO_OPEN:-0}" != "1" ]]; then
  open "$LOCAL_URL"
fi

if [[ "${SHORT_VIDEO_REVIEW_NO_DIALOG:-0}" != "1" ]]; then
  osascript -e "display dialog \"本机已打开审片页面。局域网地址已复制：$LAN_URL\" buttons {\"好\"} default button \"好\" giving up after 8" >/dev/null 2>&1 || true
else
  echo "Local: $LOCAL_URL"
  echo "LAN: $LAN_URL"
fi

if [[ -n "$SERVER_PID" ]]; then
  wait "$SERVER_PID"
fi
