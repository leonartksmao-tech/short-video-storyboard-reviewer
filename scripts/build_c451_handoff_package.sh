#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DEFAULT_PROJECT_DIR="$REPO_ROOT/0527_work"
EXAMPLE_PROJECT_DIR="$REPO_ROOT/examples"
if [[ -n "${SHORT_VIDEO_HANDOFF_PROJECT_DIR:-}" ]]; then
  PROJECT_DIR="$SHORT_VIDEO_HANDOFF_PROJECT_DIR"
elif [[ -f "$DEFAULT_PROJECT_DIR/c451_tool_output/storyboard_preview.html" ]]; then
  PROJECT_DIR="$DEFAULT_PROJECT_DIR"
elif [[ -f "$EXAMPLE_PROJECT_DIR/c451_tool_output/storyboard_preview.html" ]]; then
  PROJECT_DIR="$EXAMPLE_PROJECT_DIR"
else
  PROJECT_DIR="$DEFAULT_PROJECT_DIR"
fi
OUTPUT_DIR="${SHORT_VIDEO_HANDOFF_OUTPUT_DIR:-$REPO_ROOT}"
PACKAGE_NAME="${SHORT_VIDEO_HANDOFF_PACKAGE_NAME:-短视频审片交接包}"
PACKAGE_DIR="$OUTPUT_DIR/$PACKAGE_NAME"
ZIP_PATH="$OUTPUT_DIR/$PACKAGE_NAME.zip"

SOURCE_APP="$REPO_ROOT/短视频审片.app"
PREVIEW_PATH="$PROJECT_DIR/c451_tool_output/storyboard_preview.html"

if [[ ! -f "$PREVIEW_PATH" ]]; then
  echo "Missing preview: $PREVIEW_PATH" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_APP/Contents/Info.plist" || ! -f "$SOURCE_APP/Contents/PkgInfo" ]]; then
  echo "Missing source app template: $SOURCE_APP" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
rm -rf "$PACKAGE_DIR" "$ZIP_PATH"

APP_DIR="$PACKAGE_DIR/短视频审片.app"
APP_CONTENTS="$APP_DIR/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
PUBLIC_DIR="$APP_RESOURCES/public"

mkdir -p "$APP_MACOS" "$APP_RESOURCES"
cp "$SOURCE_APP/Contents/Info.plist" "$APP_CONTENTS/Info.plist"
cp "$SOURCE_APP/Contents/PkgInfo" "$APP_CONTENTS/PkgInfo"

ditto "$PROJECT_DIR" "$PUBLIC_DIR"
find "$PUBLIC_DIR" -name ".DS_Store" -delete

cat > "$APP_MACOS/短视频审片" <<'APP_SH'
#!/bin/zsh
set -euo pipefail

APP_EXEC_DIR="${0:A:h}"
RESOURCES_DIR="$(cd "$APP_EXEC_DIR/../Resources" && pwd)"
# Serve files embedded at 短视频审片.app/Contents/Resources/public.
SERVER_ROOT="$RESOURCES_DIR/public"
PORT="${SHORT_VIDEO_REVIEW_PORT:-8765}"
LOG_DIR="$HOME/Library/Logs/短视频审片"
LOG_FILE="$LOG_DIR/server.log"
PID_FILE="$LOG_DIR/server.pid"
PREVIEW_PATH="$SERVER_ROOT/c451_tool_output/storyboard_preview.html"

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
while port_in_use "$PORT"; do
  PORT=$((PORT + 1))
done

LOCAL_URL="http://127.0.0.1:$PORT/c451_tool_output/storyboard_preview.html"
LAN_URL="http://$LAN_IP:$PORT/c451_tool_output/storyboard_preview.html"

if [[ "${SHORT_VIDEO_REVIEW_DRY_RUN:-0}" == "1" ]]; then
  printf "SERVER_ROOT=%s\n" "$SERVER_ROOT"
  printf "LOCAL_URL=%s\n" "$LOCAL_URL"
  printf "LAN_URL=%s\n" "$LAN_URL"
  printf "PREVIEW_PATH=%s\n" "$PREVIEW_PATH"
  exit 0
fi

PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  open "$PREVIEW_PATH"
  osascript -e "display dialog \"这台 Mac 没有找到 Python 3，已用本机文件方式打开。局域网分享需要安装 Python 3。\" buttons {\"好\"} default button \"好\"" >/dev/null 2>&1 || true
  exit 0
fi

mkdir -p "$LOG_DIR"
"$PYTHON_BIN" -m http.server "$PORT" --bind 0.0.0.0 --directory "$SERVER_ROOT" > "$LOG_FILE" 2>&1 &
SERVER_PID="$!"
echo "$SERVER_PID" > "$PID_FILE"
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

if ! wait_for_server "$LOCAL_URL"; then
  osascript -e "display dialog \"审片服务启动失败，请查看：$LOG_FILE\" buttons {\"好\"} default button \"好\"" >/dev/null 2>&1 || true
  echo "Review server failed to start. Log: $LOG_FILE" >&2
  exit 1
fi

printf "%s" "$LAN_URL" | pbcopy 2>/dev/null || true

if [[ "${SHORT_VIDEO_REVIEW_NO_OPEN:-0}" != "1" ]]; then
  open "$LOCAL_URL"
fi

if [[ "${SHORT_VIDEO_REVIEW_NO_DIALOG:-0}" != "1" ]]; then
  osascript -e "display dialog \"已打开独立审片包。局域网地址已复制：$LAN_URL\" buttons {\"好\"} default button \"好\" giving up after 10" >/dev/null 2>&1 || true
else
  echo "Local: $LOCAL_URL"
  echo "LAN: $LAN_URL"
fi

wait "$SERVER_PID"
APP_SH
chmod +x "$APP_MACOS/短视频审片"

cat > "$PACKAGE_DIR/打开说明.md" <<'README'
# 短视频审片交接包

## 打开方式

双击 `短视频审片.app`。

如果 macOS 提示无法验证开发者：

1. 右键点击 `短视频审片.app`
2. 选择“打开”
3. 再点一次“打开”

## 给局域网其他电脑看

打开后弹窗会显示局域网地址，也会自动复制到剪贴板。

其他电脑需要和这台 Mac 在同一个 Wi-Fi 或局域网，然后在浏览器里打开弹窗里的地址。

## 注意

- 打开审片包的这台 Mac 不能睡眠。
- 如果防火墙询问是否允许 `Python` 接收连接，请选择允许。
- 这个包已经自带审片页面和素材，不需要原项目文件夹。
README

ditto -c -k --sequesterRsrc --keepParent "$PACKAGE_DIR" "$ZIP_PATH"

printf "PACKAGE_DIR=%s\n" "$PACKAGE_DIR"
printf "ZIP_PATH=%s\n" "$ZIP_PATH"
