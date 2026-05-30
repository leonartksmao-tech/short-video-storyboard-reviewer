import unittest

from video_md_tool import (
    main,
    parse_markdown_storyboard,
    parse_time_range,
    render_html,
    review_timeline,
    write_outputs,
)


class VideoMdToolTests(unittest.TestCase):
    def test_parse_time_range(self):
        start, end = parse_time_range("00:04.6-00:08.8")
        self.assertAlmostEqual(start, 4.6)
        self.assertAlmostEqual(end, 8.8)

    def test_parse_storyboard_table(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
| 2 | 00:04.6-00:08.8 | 来自孩子亲手做的小纸偶。 | 角色来自孩子亲手做 | 纸偶近景。 | 快速推拉。 | 纸张声。 | match cut。 |
"""
        result = parse_markdown_storyboard(md, source_file="sample.md")
        self.assertEqual(len(result.scenes), 2)
        self.assertEqual(result.scenes[0].index, 1)
        self.assertEqual(result.scenes[1].onscreen_text, "角色来自孩子亲手做")
        self.assertAlmostEqual(result.total_duration, 8.8)

    def test_review_flags_timing_and_missing_fields(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04 | 这是一句很长很长很长很长很长很长很长的口播。 | 很长很长很长很长很长很长很长很长很长很长很长很长很长 | 画面 | 剪辑 | 音效 | 特效 |
| 2 | 00:03-00:05 | 口播 | 文字 |  | 剪辑 | 音效 | 特效 |
"""
        timeline = parse_markdown_storyboard(md, source_file="sample.md")
        reviewed = review_timeline(timeline)
        messages = "\n".join(issue["message"] for issue in reviewed.issues)
        self.assertIn("时间重叠", messages)
        self.assertIn("画面内容为空", messages)
        self.assertIn("屏幕大字偏长", messages)

    def test_write_outputs_creates_expected_files(self):
        import json
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        timeline = review_timeline(parse_markdown_storyboard(md, source_file="sample.md"))
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            write_outputs(timeline, out_dir)
            expected = {
                "review_report.md",
                "storyboard_preview.html",
                "assets_checklist.md",
                "subtitles.srt",
                "timeline.json",
            }
            self.assertEqual(expected, {path.name for path in out_dir.iterdir()})
            self.assertIn("00:00:00,000 --> 00:00:04,600", (out_dir / "subtitles.srt").read_text(encoding="utf-8"))
            self.assertIn("你以为这是动画片？", (out_dir / "storyboard_preview.html").read_text(encoding="utf-8"))
            data = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
            self.assertEqual(data["scenes"][0]["index"], 1)

    def test_render_html_includes_interactive_review_controls(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
| 2 | 00:04.6-00:08.8 | 口播 | 文字 |  | 剪辑 | 音效 | 特效 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn('class="toolbar"', html)
        self.assertIn('id="sceneSearch"', html)
        self.assertIn('data-filter="issues"', html)
        self.assertIn('data-filter="unreviewed"', html)
        self.assertIn('data-action="copy-voiceover"', html)
        self.assertIn('class="review-toggle"', html)
        self.assertIn("localStorage", html)
        self.assertIn("scrollScene", html)

    def test_render_html_includes_editing_timeline_panel(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
| 2 | 00:04.6-00:08.8 | 口播 | 文字 | 纸偶近景。 | 剪辑 | 音效 | 特效 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn('id="timelinePanel"', html)
        self.assertIn('id="timelineViewport"', html)
        self.assertIn('id="timelineRuler"', html)
        self.assertIn('id="timelineTracks"', html)
        self.assertIn('id="timelinePlayhead"', html)
        self.assertIn('id="timelineZoom"', html)
        self.assertIn('data-track="video"', html)
        self.assertIn('data-track="audio"', html)
        self.assertIn('data-track="effect"', html)
        self.assertIn("renderTimeline", html)
        self.assertIn("setTimelinePlayhead", html)
        self.assertIn("updateTimelineActive", html)
        self.assertIn("formatTimelineTime", html)

    def test_render_html_uses_scene_frame_as_preview_without_program_monitor(self):
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
| 2 | 00:04.6-00:08.8 | 口播 | 文字 | 纸偶近景。 | 剪辑 | 音效 | 特效 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "story.md"
            out_dir = root / "out"
            storyboard = root / "storyboard"
            storyboard.mkdir()
            source.write_text(md, encoding="utf-8")
            (storyboard / "01_hook.mp4").write_bytes(b"mp4")

            timeline = review_timeline(parse_markdown_storyboard(source.read_text(encoding="utf-8"), source_file=str(source)))
            html = render_html(timeline, out_dir=out_dir)

        self.assertIn('class="frame', html)
        self.assertIn('<video class="scene-media"', html)
        self.assertIn('controls playsinline preload="metadata"', html)
        self.assertNotIn('id="monitorPanel"', html)
        self.assertNotIn('id="monitorScreen"', html)
        self.assertNotIn('id="monitorMediaLayer"', html)
        self.assertNotIn('data-monitor-action', html)
        self.assertNotIn("renderMonitorMedia", html)
        self.assertNotIn("updateMonitor", html)

    def test_render_html_does_not_reserve_top_space_for_program_monitor(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn("header {", html)
        self.assertIn("padding: 18px 20px 18px;", html)
        self.assertNotIn("padding: 286px 20px 18px;", html)
        self.assertNotIn(".monitor-panel", html)
        self.assertNotIn(".monitor-screen", html)

    def test_render_html_pins_timeline_full_width_to_bottom_of_viewport(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertRegex(html, r"\.timeline-panel\s*\{[^}]*position:\s*fixed;")
        self.assertRegex(html, r"\.timeline-panel\s*\{[^}]*left:\s*0;")
        self.assertRegex(html, r"\.timeline-panel\s*\{[^}]*right:\s*0;")
        self.assertRegex(html, r"\.timeline-panel\s*\{[^}]*bottom:\s*0;")
        self.assertRegex(html, r"\.timeline-panel\s*\{[^}]*z-index:\s*40;")
        self.assertRegex(html, r"\.timeline-panel\s*\{[^}]*border-radius:\s*0;")
        self.assertIn("main { padding: 22px 20px 260px; }", html)

    def test_render_html_includes_timeline_zoom_and_drag_controls(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
| 2 | 00:04.6-00:08.8 | 口播 | 文字 | 纸偶近景。 | 剪辑 | 音效 | 特效 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn('title="滚轮缩放，按住空白处拖拽平移，拖动播放头定位"', html)
        self.assertIn(".timeline-viewport.is-dragging", html)
        self.assertIn("clampTimelineZoom", html)
        self.assertIn("setTimelineZoom", html)
        self.assertIn("zoomTimelineAt", html)
        self.assertIn("beginTimelinePan", html)
        self.assertIn("beginPlayheadDrag", html)
        self.assertIn("handleTimelinePointerMove", html)
        self.assertIn("endTimelinePointerDrag", html)
        self.assertIn('addEventListener("wheel"', html)
        self.assertIn('addEventListener("pointerdown"', html)

    def test_render_html_uses_compact_scene_cards_with_portrait_preview_and_details_on_the_right(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
| 2 | 00:04.6-00:08.8 | 口播 | 文字 | 纸偶近景。 | 剪辑 | 音效 | 特效 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertRegex(html, r"\.grid\s*\{[^}]*grid-template-columns:\s*1fr;")
        self.assertRegex(html, r"\.card\s*\{[^}]*display:\s*grid;")
        self.assertRegex(html, r"\.card\s*\{[^}]*grid-template-columns:\s*minmax\(260px,\s*360px\)\s*minmax\(0,\s*1fr\);")
        self.assertRegex(html, r"\.card\s*\{[^}]*align-items:\s*start;")
        self.assertRegex(html, r"\.frame\s*\{[^}]*width:\s*min\(100%,\s*360px\);")
        self.assertRegex(html, r"\.frame\s*\{[^}]*aspect-ratio:\s*9\s*/\s*16;")
        self.assertRegex(html, r"\.frame\s*\{[^}]*justify-self:\s*center;")
        self.assertRegex(html, r"\.frame\s*\{[^}]*min-height:\s*0;")
        self.assertRegex(html, r"\.details\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\);")
        self.assertIn(".details > .clip-tool", html)

    def test_scene_cards_include_timeline_timing_data(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn('data-start="0.000"', html)
        self.assertIn('data-end="4.600"', html)
        self.assertIn('data-duration="4.600"', html)

    def test_render_html_auto_embeds_numbered_storyboard_assets(self):
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
| 2 | 00:04.6-00:08.8 | 口播 | 文字 | 纸偶近景。 | 剪辑 | 音效 | 特效 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "story.md"
            out_dir = root / "out"
            storyboard = root / "storyboard"
            storyboard.mkdir()
            source.write_text(md, encoding="utf-8")
            (storyboard / "01_hook.jpg").write_bytes(b"jpg")
            (storyboard / "02_puppet.mp4").write_bytes(b"mp4")

            timeline = review_timeline(parse_markdown_storyboard(source.read_text(encoding="utf-8"), source_file=str(source)))
            html = render_html(timeline, out_dir=out_dir)

        self.assertIn('<img class="scene-media"', html)
        self.assertIn('<video class="scene-media"', html)
        self.assertIn('src="../storyboard/01_hook.jpg"', html)
        self.assertIn('src="../storyboard/02_puppet.mp4"', html)
        self.assertIn("素材：01_hook.jpg", html)

    def test_render_html_uses_specified_asset_library_for_scene_assets(self):
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "story.md"
            out_dir = root / "out"
            library = root / "素材库"
            nested = library / "C451" / "视频"
            nested.mkdir(parents=True)
            source.write_text(md, encoding="utf-8")
            (nested / "01_library_clip.mp4").write_bytes(b"mp4")

            timeline = review_timeline(parse_markdown_storyboard(source.read_text(encoding="utf-8"), source_file=str(source)))
            html = render_html(timeline, out_dir=out_dir, asset_dirs=[library])

        self.assertIn('<video class="scene-media"', html)
        self.assertIn("01_library_clip.mp4", html)
        self.assertIn("素材库/C451/视频/01_library_clip.mp4", html)

    def test_render_html_lists_videos_from_specified_asset_library(self):
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "story.md"
            out_dir = root / "out"
            library = root / "library"
            nested = library / "raw" / "2026"
            nested.mkdir(parents=True)
            source.write_text(md, encoding="utf-8")
            (nested / "base_video.mp4").write_bytes(b"mp4")

            timeline = review_timeline(parse_markdown_storyboard(source.read_text(encoding="utf-8"), source_file=str(source)))
            html = render_html(timeline, out_dir=out_dir, asset_dirs=[library])
            expected_video_path = str((nested / "base_video.mp4").resolve())

        self.assertIn("base_video.mp4", html)
        self.assertIn("data-video-path", html)
        self.assertIn(expected_video_path, html)
        self.assertNotIn("--asset-dir", html)

    def test_render_html_includes_browser_asset_library_picker(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn('id="chooseAssetDir"', html)
        self.assertIn('id="browserAssetDir"', html)
        self.assertIn("webkitdirectory", html)
        self.assertIn('id="browserAssetStatus"', html)
        self.assertIn("applyBrowserAssets", html)
        self.assertIn("setCardMedia", html)
        self.assertIn("updateClipSourceOptions", html)
        self.assertIn("URL.createObjectURL", html)

    def test_render_html_clip_tool_available_without_initial_videos(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn('data-video-clip-panel', html)
        self.assertIn('data-video-source', html)
        self.assertIn("先选择资料库", html)
        self.assertNotIn("浏览器已载入该视频", html)

    def test_render_html_uses_video_preview_and_clip_range_slider(self):
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "story.md"
            out_dir = root / "out"
            source.write_text(md, encoding="utf-8")
            (root / "base_video.mp4").write_bytes(b"mp4")

            timeline = review_timeline(parse_markdown_storyboard(source.read_text(encoding="utf-8"), source_file=str(source)))
            html = render_html(timeline, out_dir=out_dir)

        self.assertIn('data-video-clip-panel', html)
        self.assertIn('data-video-source', html)
        self.assertIn('class="clip-editor"', html)
        self.assertIn('class="clip-preview"', html)
        self.assertIn('data-clip-preview', html)
        self.assertIn('data-clip-preview-empty', html)
        self.assertIn('data-clip-slider', html)
        self.assertIn("入点", html)
        self.assertIn("出点", html)
        self.assertIn('data-clip-in', html)
        self.assertIn('data-clip-out', html)
        self.assertIn('id="scene-1-clip-in"', html)
        self.assertIn('id="scene-1-clip-out"', html)
        self.assertRegex(html, r'id="scene-1-clip-in"[^>]*type="range"')
        self.assertRegex(html, r'id="scene-1-clip-out"[^>]*type="range"')
        self.assertIn('data-clip-in-output', html)
        self.assertIn('data-clip-out-output', html)
        self.assertIn('value="3.0"', html)
        self.assertIn("syncClipRange", html)
        self.assertIn("updateClipPreview", html)
        self.assertNotIn("开始秒", html)
        self.assertNotIn("时长秒", html)
        self.assertNotIn('data-clip-start', html)
        self.assertNotIn('data-clip-duration', html)
        self.assertNotIn('data-clip-command', html)
        self.assertNotIn('data-action="preview-video-clip"', html)
        self.assertNotIn('data-action="copy-clip-command"', html)
        self.assertNotIn("预览片段", html)
        self.assertNotIn("复制截取命令", html)
        self.assertNotIn("先选择资料库，或用终端 --asset-dir 指定资料库后重新生成。", html)
        self.assertIn("base_video.mp4", html)

    def test_main_accepts_asset_dir(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:02 | 测试口播。 | 测试大字 | 测试画面 | 测试剪辑 | 测试音效 | 测试特效 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "story.md"
            out_dir = temp_path / "out"
            library = temp_path / "library"
            library.mkdir()
            source.write_text(md, encoding="utf-8")
            (library / "01_asset.jpg").write_bytes(b"jpg")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(source), "--out", str(out_dir), "--asset-dir", str(library)])

            self.assertEqual(exit_code, 0)
            html = (out_dir / "storyboard_preview.html").read_text(encoding="utf-8")
            self.assertIn("01_asset.jpg", html)
            self.assertIn("Asset dirs: 1", stdout.getvalue())

    def test_video_clip_asset_overrides_scene_image(self):
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "story.md"
            out_dir = root / "out"
            storyboard = root / "storyboard"
            storyboard.mkdir()
            source.write_text(md, encoding="utf-8")
            (storyboard / "01_hook.jpg").write_bytes(b"jpg")
            (storyboard / "01_clip_0000_0300.mp4").write_bytes(b"mp4")

            timeline = review_timeline(parse_markdown_storyboard(source.read_text(encoding="utf-8"), source_file=str(source)))
            html = render_html(timeline, out_dir=out_dir)

        self.assertIn('<video class="scene-media"', html)
        self.assertIn('src="../storyboard/01_clip_0000_0300.mp4"', html)
        self.assertNotIn('src="../storyboard/01_hook.jpg"', html)

    def test_render_html_includes_editable_fields_and_sound_presets(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn('id="exportEdits"', html)
        self.assertIn('id="resetEdits"', html)
        self.assertIn('data-edit-field="voiceover"', html)
        self.assertIn('data-edit-field="edit_action"', html)
        self.assertIn('data-edit-field="sound"', html)
        self.assertIn('data-edit-field="effect"', html)
        self.assertIn('data-action="append-preset"', html)
        self.assertIn("轻 whoosh", html)
        self.assertIn("温暖BGM", html)
        self.assertIn("storyboard-edits", html)
        self.assertIn("exportEditedScenes", html)

    def test_sound_presets_preview_before_confirming_add(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn('data-action="preview-preset"', html)
        self.assertIn('id="soundPreviewPanel"', html)
        self.assertIn('id="confirmPreset"', html)
        self.assertIn('id="cancelPreset"', html)
        self.assertIn("playPresetPreview", html)
        self.assertIn("pendingPreset", html)
        self.assertIn("加入到本格", html)

    def test_render_html_includes_drag_reordering_controls(self):
        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:04.6 | 你看看这个。 | 你以为这是动画片？ | AI 动画结果。 | 轻推近。 | BGM 进入。 | 闪白。 |
| 2 | 00:04.6-00:08.8 | 口播 | 文字 | 纸偶近景。 | 剪辑 | 音效 | 特效 |
"""
        html = render_html(review_timeline(parse_markdown_storyboard(md, source_file="sample.md")))
        self.assertIn('data-drag-handle', html)
        self.assertIn('draggable="true"', html)
        self.assertIn("拖动排序", html)
        self.assertIn("storyboard-order", html)
        self.assertIn("applySavedOrder", html)
        self.assertIn("syncCardsFromDom", html)
        self.assertIn("saveOrder", html)
        self.assertIn('id="resetOrder"', html)
        self.assertIn("position:", html)

    def test_parse_public_example_markdown(self):
        from pathlib import Path

        source = Path("examples/storyboard_sample.md")
        timeline = review_timeline(parse_markdown_storyboard(source.read_text(encoding="utf-8"), source_file=str(source)))
        self.assertEqual(len(timeline.scenes), 12)
        self.assertGreater(timeline.total_duration, 59.0)
        self.assertLess(timeline.total_duration, 60.0)
        self.assertTrue(any("总时长" in issue["message"] for issue in timeline.issues))

    def test_main_generates_outputs(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:02 | 测试口播。 | 测试大字 | 测试画面 | 测试剪辑 | 测试音效 | 测试特效 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "story.md"
            out_dir = temp_path / "out"
            source.write_text(md, encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(source), "--out", str(out_dir)])
            self.assertEqual(exit_code, 0)
            self.assertTrue((out_dir / "storyboard_preview.html").exists())
            self.assertIn("Scenes: 1", stdout.getvalue())

    def test_timeline_json_uses_stable_source_timestamp(self):
        import json
        import os
        import tempfile
        from pathlib import Path

        md = """
## 12格文字脚本

| 格 | 时间 | 原声口播 / 字幕 | 屏幕大字 | 画面内容 | 剪辑动作 | 音效 / BGM | 画面特效 / 转场 |
|---:|---|---|---|---|---|---|---|
| 1 | 00:00-00:02 | 测试口播。 | 测试大字 | 测试画面 | 测试剪辑 | 测试音效 | 测试特效 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "story.md"
            out_dir = temp_path / "out"
            source.write_text(md, encoding="utf-8")
            os.utime(source, (1700000000, 1700000000))
            timeline = review_timeline(parse_markdown_storyboard(source.read_text(encoding="utf-8"), source_file=str(source)))
            write_outputs(timeline, out_dir)
            data = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
            self.assertEqual(data["generated_at"], "2023-11-14T22:13:20Z")


if __name__ == "__main__":
    unittest.main()
