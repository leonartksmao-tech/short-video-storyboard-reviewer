# 短视频审片 App 使用说明

## 打开

双击项目根目录里的 `短视频审片.app`。

打开前需要先生成审片页面：

```bash
python3 video_md_tool.py examples/storyboard_sample.md --out examples/c451_tool_output
SHORT_VIDEO_REVIEW_PROJECT_DIR=examples scripts/serve_c451_review.sh
```

App 会自动：

- 启动本机审片网页服务
- 打开本机预览页
- 复制局域网访问地址到剪贴板
- 弹窗显示局域网地址

## 局域网访问

其他电脑需要和这台 Mac 在同一个 Wi-Fi 或局域网。

默认地址格式：

```text
http://本机局域网IP:8765/c451_tool_output/storyboard_preview.html
```

如果 `8765` 被占用，启动器会自动换到下一个可用端口，并在弹窗里显示实际地址。

## 终端启动

也可以在项目根目录运行：

```bash
scripts/serve_c451_review.sh
```

可选环境变量：

```bash
SHORT_VIDEO_REVIEW_PORT=9876 scripts/serve_c451_review.sh
SHORT_VIDEO_REVIEW_PROJECT_DIR=/path/to/work scripts/serve_c451_review.sh
```

## 注意

- 这台 Mac 不能睡眠，否则其他电脑会断开。
- 如果 macOS 防火墙弹窗询问是否允许连接，请允许 `Python` 或 `Terminal`。
- 公开仓库不包含真实视频、音频和客户素材；请用 `SHORT_VIDEO_REVIEW_PROJECT_DIR` 指向你自己的项目目录。
