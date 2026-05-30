#!/usr/bin/env python3
"""Generate review artifacts from a short-video storyboard Markdown file."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from html import escape, unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
ASSET_SEARCH_DIRS = ("storyboard", "frames", "assets", "media", ".")
KNOWN_FFMPEG_PATHS = (
    "/Applications/Memo.app/Contents/Resources/addon/ffmpeg/ffmpeg",
    "/Applications/VideoFusion-macOS.app/Contents/Resources/ffmpeg",
)
SOUND_PRESETS = (
    "轻 whoosh",
    "短促 reveal",
    "轻 pop",
    "轻 tap",
    "轻 click",
    "纸张摩擦声",
    "翻页声",
    "低频点",
    "温暖BGM",
    "轻快BGM",
    "结尾 shimmer",
)


@dataclass
class Scene:
    index: int
    raw_time: str
    start: Optional[float]
    end: Optional[float]
    duration: Optional[float]
    voiceover: str
    onscreen_text: str
    visual: str
    edit_action: str
    sound: str
    effect: str
    issues: List[str] = field(default_factory=list)


@dataclass
class SceneAsset:
    path: Path
    kind: str


@dataclass
class Timeline:
    source_file: str
    title: str
    scenes: List[Scene]
    issues: List[dict] = field(default_factory=list)

    @property
    def total_duration(self) -> float:
        ends = [scene.end for scene in self.scenes if scene.end is not None]
        return max(ends) if ends else 0.0


def parse_time_range(value: str) -> Tuple[float, float]:
    parts = re.split(r"\s*[-–—]\s*", value.strip(), maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"invalid time range: {value}")
    return _parse_time(parts[0]), _parse_time(parts[1])


def parse_markdown_storyboard(markdown_text: str, source_file: str) -> Timeline:
    title = _extract_title(markdown_text)
    rows = _extract_storyboard_rows(markdown_text)
    scenes = [_row_to_scene(row) for row in rows]
    return Timeline(source_file=source_file, title=title, scenes=scenes)


def review_timeline(timeline: Timeline) -> Timeline:
    timeline.issues = []
    for scene in timeline.scenes:
        scene.issues = []

    if not timeline.scenes:
        _add_issue(timeline, "必须修复", "-", "没有解析到 12 格文字脚本表格")
        return timeline

    for scene in timeline.scenes:
        _review_required_fields(timeline, scene)
        _review_scene_timing(timeline, scene)
        _review_text_density(timeline, scene)

    _review_timing_sequence(timeline)
    _review_total_duration(timeline)
    _review_keyword_coverage(timeline)
    return timeline


def format_srt_time(seconds: float) -> str:
    milliseconds_total = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds_total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def render_review_report(timeline: Timeline) -> str:
    lines = [
        f"# {timeline.title} 审查报告",
        "",
        f"- 来源：`{timeline.source_file}`",
        f"- 分镜数量：{len(timeline.scenes)}",
        f"- 总时长：{timeline.total_duration:.1f} 秒",
        f"- 问题数量：{len(timeline.issues)}",
        "",
    ]

    for severity in ("必须修复", "建议修改", "仅供参考"):
        issues = [issue for issue in timeline.issues if issue["severity"] == severity]
        lines.extend([f"## {severity}", ""])
        if not issues:
            lines.extend(["- 无", ""])
            continue
        for issue in issues:
            scene = issue["scene"]
            prefix = f"第 {scene} 格" if scene != "-" else "全片"
            lines.append(f"- {prefix}：{issue['message']}")
        lines.append("")

    lines.extend(["## 分镜概览", ""])
    for scene in timeline.scenes:
        lines.extend(
            [
                f"### 第 {scene.index} 格 {scene.raw_time}",
                "",
                f"- 屏幕大字：{scene.onscreen_text or '空'}",
                f"- 口播：{scene.voiceover or '空'}",
                f"- 画面：{scene.visual or '空'}",
                f"- 剪辑：{scene.edit_action or '空'}",
                f"- 音效 / BGM：{scene.sound or '空'}",
                f"- 特效 / 转场：{scene.effect or '空'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_assets_checklist(timeline: Timeline) -> str:
    lines = [
        f"# {timeline.title} 素材清单",
        "",
        f"来源：`{timeline.source_file}`",
        "",
    ]
    for scene in timeline.scenes:
        lines.extend(
            [
                f"## 第 {scene.index} 格 {scene.raw_time}",
                "",
                f"- 画面需求：{scene.visual or '空'}",
                f"- 可能需要的素材类型：{_guess_asset_type(scene)}",
                f"- 剪辑备注：{scene.edit_action or '空'}",
                f"- 屏幕文字：{scene.onscreen_text or '空'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_srt(timeline: Timeline) -> str:
    blocks = []
    for index, scene in enumerate(timeline.scenes, start=1):
        if scene.start is None or scene.end is None:
            continue
        subtitle = scene.voiceover or scene.onscreen_text
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_time(scene.start)} --> {format_srt_time(scene.end)}",
                    subtitle,
                ]
            )
        )
    return "\n\n".join(blocks).rstrip() + "\n"


def render_html(
    timeline: Timeline,
    out_dir: Optional[Path] = None,
    asset_dirs: Optional[Sequence[Path]] = None,
) -> str:
    normalized_asset_dirs = _normalize_asset_dirs(asset_dirs)
    cards = "\n".join(
        _render_scene_card(
            scene,
            _find_scene_asset(scene, timeline.source_file, normalized_asset_dirs),
            out_dir,
            timeline.source_file,
            normalized_asset_dirs,
        )
        for scene in timeline.scenes
    )
    summary = _render_issue_summary(timeline)
    toolbar = _render_toolbar()
    timeline_panel = _render_timeline_panel(timeline)
    script = _render_interaction_script()
    source_path = str(Path(timeline.source_file).resolve())
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(timeline.title)} 分镜预览</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #16746f;
      --warn: #b25e09;
      --bad: #b42318;
      --soft: #eef7f6;
      --active: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    header {{
      padding: 18px 20px 18px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    .wrap {{ max-width: 1180px; margin: 0 auto; }}
    h1 {{ margin: 0 0 12px; font-size: 28px; line-height: 1.2; letter-spacing: 0; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 10px; color: var(--muted); }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 10px;
      background: #fff;
      font-size: 13px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-top: 16px;
    }}
    .summary div {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      background: var(--soft);
      font-size: 14px;
    }}
    .toolbar {{
      display: grid;
      grid-template-columns: minmax(180px, 1fr) auto auto;
      gap: 10px;
      align-items: center;
      margin-top: 16px;
    }}
    .search {{
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 12px;
      color: var(--ink);
      background: #fff;
      font-size: 14px;
    }}
    .segmented, .toolbar-actions, .scene-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }}
    button, .review-control {{
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 6px 10px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      cursor: pointer;
    }}
    button:hover, .review-control:hover {{ border-color: var(--active); }}
    button[aria-pressed="true"] {{
      border-color: var(--active);
      background: var(--active);
      color: #fff;
    }}
    .review-control {{
      display: inline-flex;
      gap: 6px;
      align-items: center;
      user-select: none;
    }}
    main {{ padding: 22px 20px 260px; }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
    }}
    .card {{
      display: grid;
      grid-template-columns: minmax(260px, 360px) minmax(0, 1fr);
      align-items: start;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }}
    .card.has-issues {{ border-color: #e5a000; }}
    .card.is-active {{
      outline: 3px solid rgba(15, 118, 110, 0.24);
      outline-offset: 2px;
    }}
    .card.is-reviewed {{ border-color: #9cc7bf; }}
    .card.is-hidden {{ display: none; }}
    .card.is-dragging {{
      opacity: 0.58;
      transform: scale(0.99);
    }}
    .card.is-drop-target {{
      box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.18);
    }}
    .frame {{
      width: min(100%, 360px);
      aspect-ratio: 9 / 16;
      justify-self: center;
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 0;
      padding: 18px;
      overflow: hidden;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.76)),
        repeating-linear-gradient(45deg, #eef1f5, #eef1f5 10px, #e4e8ef 10px, #e4e8ef 20px);
    }}
    .frame.has-media {{
      padding: 0;
      background: #111827;
      color: #fff;
    }}
    .frame.has-media::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(0,0,0,0.50), rgba(0,0,0,0.12) 42%, rgba(0,0,0,0.62));
      pointer-events: none;
      z-index: 1;
    }}
    .scene-media {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      background: #111827;
    }}
    .frame-content {{
      position: relative;
      z-index: 2;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 100%;
      padding: 18px;
    }}
    .time {{ font-weight: 700; color: var(--accent); font-size: 14px; }}
    .frame.has-media .time {{ color: #d8fffb; text-shadow: 0 1px 2px rgba(0,0,0,0.45); }}
    .frame-top {{
      display: flex;
      gap: 8px;
      justify-content: space-between;
      align-items: flex-start;
    }}
    .bigtext {{ font-size: 24px; font-weight: 800; line-height: 1.25; overflow-wrap: anywhere; }}
    .visual {{ color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }}
    .frame.has-media .bigtext, .frame.has-media .visual {{
      text-shadow: 0 1px 3px rgba(0,0,0,0.55);
    }}
    .frame.has-media .visual {{ color: rgba(255,255,255,0.88); }}
    .asset-label {{
      align-self: flex-start;
      max-width: 100%;
      margin-top: 10px;
      border: 1px solid rgba(255,255,255,0.32);
      border-radius: 8px;
      padding: 4px 7px;
      background: rgba(0,0,0,0.38);
      color: #fff;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .body {{
      min-width: 0;
      padding: 14px 16px 16px;
    }}
    .scene-actions {{
      margin-bottom: 12px;
      justify-content: space-between;
    }}
    .scene-actions-left, .scene-actions-right {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }}
    .drag-handle {{
      cursor: grab;
      user-select: none;
    }}
    .drag-handle:active {{
      cursor: grabbing;
    }}
    .browser-asset-status {{
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
    }}
    .timeline-panel {{
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: 40;
      margin: 0;
      border: 1px solid #263242;
      border-radius: 0;
      overflow: hidden;
      background: #111923;
      color: #e8edf2;
      box-shadow: 0 18px 60px rgba(15, 23, 42, 0.35);
    }}
    .timeline-header {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      border-bottom: 1px solid rgba(255,255,255,0.12);
      background: #151f2b;
    }}
    .timeline-title {{
      font-weight: 800;
      font-size: 14px;
    }}
    .timeline-readout {{
      display: flex;
      gap: 8px;
      align-items: center;
      color: #b8c4d2;
      font-size: 12px;
    }}
    .timeline-readout strong {{
      color: #fff;
      font-size: 13px;
    }}
    .timeline-zoom {{
      display: inline-flex;
      gap: 8px;
      align-items: center;
      color: #b8c4d2;
      font-size: 12px;
    }}
    .timeline-zoom input {{
      width: 120px;
      accent-color: #18a39b;
    }}
    .timeline-viewport {{
      position: relative;
      overflow-x: auto;
      overflow-y: hidden;
      background: #0d141d;
      cursor: grab;
      user-select: none;
      touch-action: pan-y;
    }}
    .timeline-viewport.is-dragging {{
      cursor: grabbing;
    }}
    .timeline-viewport.is-dragging * {{
      cursor: grabbing;
    }}
    .timeline-canvas {{
      position: relative;
      min-width: 100%;
      padding-bottom: 10px;
    }}
    .timeline-ruler {{
      position: relative;
      height: 30px;
      margin-left: 52px;
      border-left: 1px solid rgba(255,255,255,0.16);
    }}
    .timeline-tick {{
      position: absolute;
      top: 0;
      width: 1px;
      height: 30px;
      background: rgba(255,255,255,0.16);
    }}
    .timeline-tick span {{
      position: absolute;
      top: 6px;
      left: 5px;
      color: #8c9aaa;
      font-size: 11px;
      white-space: nowrap;
    }}
    .timeline-tracks {{
      border-top: 1px solid rgba(255,255,255,0.12);
    }}
    .timeline-track {{
      display: grid;
      grid-template-columns: 52px 1fr;
      min-height: 44px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
    }}
    .timeline-track-label {{
      display: flex;
      align-items: center;
      justify-content: center;
      border-right: 1px solid rgba(255,255,255,0.12);
      background: #101923;
      color: #b8c4d2;
      font-size: 12px;
      font-weight: 800;
    }}
    .timeline-lane {{
      position: relative;
      min-height: 44px;
      background-image: linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px);
      background-size: 86px 100%;
    }}
    .timeline-clip {{
      position: absolute;
      top: 7px;
      display: flex;
      gap: 6px;
      align-items: center;
      height: 30px;
      min-height: 30px;
      min-width: 22px;
      border: 1px solid rgba(255,255,255,0.18);
      border-radius: 6px;
      padding: 0 8px;
      overflow: hidden;
      color: #fff;
      font-size: 12px;
      white-space: nowrap;
      cursor: pointer;
    }}
    .timeline-clip:hover {{
      filter: brightness(1.08);
    }}
    .timeline-clip.is-active {{
      outline: 2px solid #f9c74f;
      outline-offset: 1px;
    }}
    .timeline-clip-index {{
      flex: 0 0 auto;
      width: 18px;
      height: 18px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      background: rgba(0,0,0,0.28);
      font-size: 11px;
      font-weight: 800;
    }}
    .timeline-clip-label {{
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .timeline-clip-video {{ background: #1c6f8d; }}
    .timeline-clip-audio {{ background: #6b7f2a; }}
    .timeline-clip-effect {{ background: #8d4f9f; }}
    .timeline-playhead {{
      position: absolute;
      top: 0;
      bottom: 0;
      left: 52px;
      z-index: 4;
      width: 10px;
      transform: translateX(-5px);
      background: transparent;
      cursor: ew-resize;
      pointer-events: auto;
      touch-action: none;
    }}
    .timeline-playhead::after {{
      content: "";
      position: absolute;
      top: 0;
      bottom: 0;
      left: 4px;
      width: 2px;
      background: #f59e0b;
    }}
    .timeline-playhead::before {{
      content: "";
      position: absolute;
      top: 0;
      left: -1px;
      border-left: 6px solid transparent;
      border-right: 6px solid transparent;
      border-top: 8px solid #f59e0b;
    }}
    .details[hidden] {{ display: none; }}
    .details {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px 12px;
      align-items: start;
    }}
    .details > .row {{
      min-width: 0;
      margin: 0;
    }}
    .details > .clip-tool, .details > .issues {{
      grid-column: 1 / -1;
    }}
    .row {{ margin: 0 0 10px; }}
    .label {{ color: var(--muted); font-size: 12px; font-weight: 700; margin-bottom: 2px; }}
    .text {{ font-size: 14px; overflow-wrap: anywhere; }}
    .edit-field {{
      width: 100%;
      min-height: 68px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 9px;
      resize: vertical;
      color: var(--ink);
      background: #fff;
      font: inherit;
      font-size: 14px;
      line-height: 1.45;
    }}
    .edit-field:focus {{
      outline: 2px solid rgba(15, 118, 110, 0.24);
      border-color: var(--active);
    }}
    .card.is-edited {{
      box-shadow: inset 0 0 0 2px rgba(15, 118, 110, 0.18);
    }}
    .preset-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-top: 8px;
    }}
    .preset-bar button {{
      min-height: 28px;
      padding: 4px 8px;
      font-size: 12px;
    }}
    .clip-tool {{
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    .clip-source {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 9px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
    }}
    .clip-editor {{
      display: grid;
      grid-template-columns: minmax(160px, 260px) minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      margin-top: 10px;
    }}
    .clip-preview-box {{
      position: relative;
      aspect-ratio: 16 / 9;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #111827;
    }}
    .clip-preview {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
      background: #111827;
    }}
    .clip-preview-empty {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 10px;
      background: linear-gradient(135deg, #111827, #1f2937);
      color: #d6dee8;
      font-size: 12px;
      text-align: center;
    }}
    .clip-preview-empty[hidden] {{ display: none; }}
    .clip-trim {{
      display: grid;
      gap: 10px;
      min-width: 0;
    }}
    .clip-trim-head {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 16px;
      justify-content: space-between;
    }}
    .clip-trim-head label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .clip-trim-head output {{
      display: inline-block;
      margin-left: 4px;
      color: var(--ink);
      font-size: 13px;
      font-weight: 800;
    }}
    .clip-slider {{
      --clip-in-percent: 0%;
      --clip-out-percent: 100%;
      position: relative;
      display: grid;
      align-items: center;
      min-height: 36px;
    }}
    .clip-slider::before {{
      content: "";
      grid-area: 1 / 1;
      width: 100%;
      height: 6px;
      border-radius: 999px;
      background: linear-gradient(
        90deg,
        #d9dee7 0 var(--clip-in-percent),
        var(--active) var(--clip-in-percent) var(--clip-out-percent),
        #d9dee7 var(--clip-out-percent) 100%
      );
    }}
    .clip-slider input[type="range"] {{
      grid-area: 1 / 1;
      width: 100%;
      margin: 0;
      appearance: none;
      background: transparent;
      pointer-events: none;
    }}
    .clip-slider input[type="range"]::-webkit-slider-runnable-track {{
      height: 6px;
      background: transparent;
    }}
    .clip-slider input[type="range"]::-webkit-slider-thumb {{
      width: 18px;
      height: 18px;
      margin-top: -6px;
      border: 2px solid #fff;
      border-radius: 999px;
      appearance: none;
      background: var(--active);
      box-shadow: 0 1px 5px rgba(15, 23, 42, 0.28);
      cursor: ew-resize;
      pointer-events: auto;
    }}
    .clip-slider input[type="range"]::-moz-range-track {{
      height: 6px;
      background: transparent;
    }}
    .clip-slider input[type="range"]::-moz-range-thumb {{
      width: 18px;
      height: 18px;
      border: 2px solid #fff;
      border-radius: 999px;
      background: var(--active);
      box-shadow: 0 1px 5px rgba(15, 23, 42, 0.28);
      cursor: ew-resize;
      pointer-events: auto;
    }}
    .sound-preview-panel {{
      position: fixed;
      right: 18px;
      bottom: 238px;
      z-index: 20;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      max-width: min(92vw, 560px);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fff;
      box-shadow: 0 16px 42px rgba(15, 23, 42, 0.18);
    }}
    .sound-preview-panel[hidden] {{ display: none; }}
    .sound-preview-copy {{
      flex: 1 1 180px;
      color: var(--muted);
      font-size: 13px;
    }}
    .sound-preview-copy strong {{
      display: block;
      color: var(--ink);
      font-size: 14px;
    }}
    .sound-preview-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .issues {{
      margin-top: 12px;
      border-top: 1px solid var(--line);
      padding-top: 10px;
      color: var(--warn);
      font-size: 13px;
    }}
    .empty-state {{
      display: none;
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 18px;
      background: #fff;
      color: var(--muted);
      text-align: center;
    }}
    .empty-state.is-visible {{ display: block; }}
    .toast {{
      position: fixed;
      left: 50%;
      bottom: 242px;
      transform: translateX(-50%);
      max-width: min(92vw, 360px);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      background: #17202a;
      color: #fff;
      font-size: 13px;
      opacity: 0;
      pointer-events: none;
      transition: opacity 160ms ease;
    }}
    .toast.is-visible {{ opacity: 1; }}
    @media (max-width: 640px) {{
      h1 {{ font-size: 22px; }}
      main {{ padding-left: 12px; padding-right: 12px; padding-bottom: 250px; }}
      .grid {{ grid-template-columns: 1fr; }}
      .card {{ grid-template-columns: 1fr; }}
      .frame {{ min-height: 0; }}
      .details {{ grid-template-columns: 1fr; }}
      .bigtext {{ font-size: 22px; }}
      .toolbar {{ grid-template-columns: 1fr; }}
      .segmented, .toolbar-actions {{ width: 100%; }}
      .segmented button, .toolbar-actions button {{ flex: 1 1 auto; }}
      .timeline-panel {{ left: 0; right: 0; bottom: 0; }}
      .timeline-header {{ align-items: flex-start; }}
      .timeline-zoom {{ width: 100%; }}
      .timeline-zoom input {{ flex: 1 1 auto; }}
      .timeline-ruler {{ height: 24px; }}
      .timeline-track, .timeline-lane {{ min-height: 38px; }}
      .timeline-clip {{ top: 6px; height: 26px; min-height: 26px; }}
      .clip-editor {{ grid-template-columns: 1fr; }}
      .sound-preview-panel {{ right: 10px; bottom: 228px; }}
      .toast {{ bottom: 232px; }}
    }}
  </style>
</head>
<body data-source="{_html_attr(timeline.source_file)}" data-source-path="{_html_attr(source_path)}">
  <header>
    <div class="wrap">
      <h1>{escape(timeline.title)}</h1>
      <div class="meta">
        <span class="pill">来源：{escape(timeline.source_file)}</span>
        <span class="pill">分镜：{len(timeline.scenes)} 格</span>
        <span class="pill">总时长：{timeline.total_duration:.1f} 秒</span>
        <span class="pill">问题：{len(timeline.issues)} 条</span>
      </div>
      {summary}
      {toolbar}
      {timeline_panel}
    </div>
  </header>
  <main>
    <div class="wrap">
      <div id="emptyState" class="empty-state">没有符合条件的分镜</div>
      <div id="sceneGrid" class="grid">
        {cards}
      </div>
    </div>
  </main>
  <div id="soundPreviewPanel" class="sound-preview-panel" hidden>
    <div class="sound-preview-copy">
      <strong id="pendingPresetLabel">试听音效</strong>
      <span id="pendingSceneLabel">确认后再加入到分镜音效框</span>
    </div>
    <div class="sound-preview-actions">
      <button type="button" id="replayPreset">再听一次</button>
      <button type="button" id="confirmPreset" data-action="append-preset">加入到本格</button>
      <button type="button" id="cancelPreset">取消</button>
    </div>
  </div>
  <div id="toast" class="toast" role="status" aria-live="polite"></div>
  {script}
</body>
</html>
"""


def timeline_to_dict(timeline: Timeline) -> Dict[str, Any]:
    return {
        "source_file": timeline.source_file,
        "generated_at": _source_generated_at(timeline.source_file),
        "title": timeline.title,
        "total_duration": timeline.total_duration,
        "issues": timeline.issues,
        "scenes": [
            {
                "index": scene.index,
                "raw_time": scene.raw_time,
                "start": scene.start,
                "end": scene.end,
                "duration": scene.duration,
                "voiceover": scene.voiceover,
                "onscreen_text": scene.onscreen_text,
                "visual": scene.visual,
                "edit_action": scene.edit_action,
                "sound": scene.sound,
                "effect": scene.effect,
                "issues": scene.issues,
            }
            for scene in timeline.scenes
        ],
    }


def write_outputs(
    timeline: Timeline,
    out_dir: Path,
    asset_dirs: Optional[Sequence[Path]] = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "review_report.md").write_text(render_review_report(timeline), encoding="utf-8")
    (out_dir / "storyboard_preview.html").write_text(
        render_html(timeline, out_dir=out_dir, asset_dirs=asset_dirs),
        encoding="utf-8",
    )
    (out_dir / "assets_checklist.md").write_text(render_assets_checklist(timeline), encoding="utf-8")
    (out_dir / "subtitles.srt").write_text(render_srt(timeline), encoding="utf-8")
    (out_dir / "timeline.json").write_text(
        json.dumps(timeline_to_dict(timeline), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate review artifacts from a short-video storyboard Markdown file."
    )
    parser.add_argument("input_md", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--clip-scene", type=int, help="Clip a source video into the numbered storyboard slot.")
    parser.add_argument("--clip-source", type=Path, help="Source video to clip for --clip-scene.")
    parser.add_argument("--clip-start", type=float, default=0.0, help="Clip start time in seconds.")
    parser.add_argument("--clip-duration", type=float, default=3.0, help="Clip duration in seconds.")
    parser.add_argument("--clip-out", type=Path, help="Optional output path for the clipped scene video.")
    parser.add_argument("--ffmpeg", type=Path, help="Optional ffmpeg binary path.")
    parser.add_argument(
        "--asset-dir",
        type=Path,
        action="append",
        default=[],
        help="Additional material library folder to scan. Can be repeated.",
    )
    args = parser.parse_args(argv)

    if not args.input_md.exists():
        print(f"ERROR: input file not found: {args.input_md}", file=sys.stderr)
        return 2
    asset_dirs = _normalize_asset_dirs(args.asset_dir)
    missing_asset_dirs = [path for path in asset_dirs if not path.exists() or not path.is_dir()]
    if missing_asset_dirs:
        print(f"ERROR: asset dir not found: {missing_asset_dirs[0]}", file=sys.stderr)
        return 2

    clip_path: Optional[Path] = None
    if args.clip_scene is not None or args.clip_source is not None:
        if args.clip_scene is None or args.clip_source is None:
            print("ERROR: --clip-scene and --clip-source must be used together", file=sys.stderr)
            return 2
        try:
            clip_path = clip_video_for_scene(
                args.input_md,
                args.clip_scene,
                args.clip_source,
                args.clip_start,
                args.clip_duration,
                output_path=args.clip_out,
                ffmpeg_path=args.ffmpeg,
            )
        except (OSError, RuntimeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1

    out_dir = args.out or args.input_md.parent / "c451_tool_output"
    text = args.input_md.read_text(encoding="utf-8")
    timeline = review_timeline(parse_markdown_storyboard(text, source_file=str(args.input_md)))
    write_outputs(timeline, out_dir, asset_dirs=asset_dirs)

    if clip_path:
        print(f"Clipped: {clip_path}")
    print(f"Generated: {out_dir}")
    print(f"Scenes: {len(timeline.scenes)}")
    print(f"Issues: {len(timeline.issues)}")
    if asset_dirs:
        print(f"Asset dirs: {len(asset_dirs)}")
    return 0


def clip_video_for_scene(
    input_md: Path,
    scene_index: int,
    source_video: Path,
    start: float,
    duration: float,
    output_path: Optional[Path] = None,
    ffmpeg_path: Optional[Path] = None,
) -> Path:
    if scene_index <= 0:
        raise ValueError("--clip-scene must be greater than 0")
    if start < 0:
        raise ValueError("--clip-start must be 0 or greater")
    if duration <= 0:
        raise ValueError("--clip-duration must be greater than 0")
    if not source_video.exists():
        raise FileNotFoundError(f"clip source not found: {source_video}")

    output = output_path or _scene_clip_output_path(input_md, scene_index, start, duration)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _find_ffmpeg(ffmpeg_path)
    command = _ffmpeg_clip_command(ffmpeg, source_video, output, start, duration)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip().splitlines()
        tail = "\n".join(stderr[-8:]) if stderr else "ffmpeg failed without stderr"
        raise RuntimeError(tail)
    return output


def _scene_clip_output_path(input_md: Path, scene_index: int, start: float, duration: float) -> Path:
    return input_md.parent / "storyboard" / (
        f"{scene_index:02d}_clip_{_time_token(start)}_{_time_token(duration)}.mp4"
    )


def _time_token(seconds: float) -> str:
    return f"{int(round(seconds * 100)):04d}"


def _find_ffmpeg(explicit_path: Optional[Path] = None) -> Path:
    candidates: List[Path] = []
    if explicit_path:
        candidates.append(explicit_path)
    if os.environ.get("FFMPEG"):
        candidates.append(Path(os.environ["FFMPEG"]))
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(Path(which))
    candidates.extend(Path(path) for path in KNOWN_FFMPEG_PATHS)

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError("ffmpeg not found; pass --ffmpeg or install ffmpeg")


def _ffmpeg_clip_command(ffmpeg: Path, source_video: Path, output_path: Path, start: float, duration: float) -> List[str]:
    return [
        str(ffmpeg),
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source_video),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def _parse_time(value: str) -> float:
    value = value.strip()
    segments = value.split(":")
    if len(segments) == 1:
        return float(segments[0])
    if len(segments) == 2:
        minutes = int(segments[0])
        seconds = float(segments[1])
        return minutes * 60 + seconds
    if len(segments) == 3:
        hours = int(segments[0])
        minutes = int(segments[1])
        seconds = float(segments[2])
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(f"invalid time value: {value}")


def _extract_title(markdown_text: str) -> str:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "短视频分镜脚本"


def _extract_storyboard_rows(markdown_text: str) -> List[List[str]]:
    lines = markdown_text.splitlines()
    rows: List[List[str]] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if not in_table:
            if stripped.startswith("|") and "原声口播" in stripped and "屏幕大字" in stripped:
                in_table = True
            continue

        if not stripped:
            if rows:
                break
            continue
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        if _is_separator_row(stripped):
            continue

        cells = _split_markdown_row(stripped)
        if len(cells) >= 8 and cells[0].strip() != "格":
            rows.append(cells[:8])

    return rows


def _is_separator_row(row: str) -> bool:
    cells = _split_markdown_row(row)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _split_markdown_row(row: str) -> List[str]:
    stripped = row.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [_clean_cell(cell) for cell in stripped.split("|")]


def _clean_cell(value: str) -> str:
    value = unescape(value)
    value = value.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _row_to_scene(row: Sequence[str]) -> Scene:
    index = _parse_index(row[0])
    raw_time = row[1]
    start: Optional[float]
    end: Optional[float]
    duration: Optional[float]
    try:
        start, end = parse_time_range(raw_time)
        duration = end - start
    except ValueError:
        start = None
        end = None
        duration = None

    return Scene(
        index=index,
        raw_time=raw_time,
        start=start,
        end=end,
        duration=duration,
        voiceover=row[2],
        onscreen_text=row[3],
        visual=row[4],
        edit_action=row[5],
        sound=row[6],
        effect=row[7],
    )


def _parse_index(value: str) -> int:
    match = re.search(r"\d+", value)
    if not match:
        return 0
    return int(match.group(0))


def _review_required_fields(timeline: Timeline, scene: Scene) -> None:
    fields = [
        ("时间", scene.raw_time),
        ("原声口播 / 字幕", scene.voiceover),
        ("屏幕大字", scene.onscreen_text),
        ("画面内容", scene.visual),
        ("剪辑动作", scene.edit_action),
        ("音效 / BGM", scene.sound),
        ("画面特效 / 转场", scene.effect),
    ]
    for label, value in fields:
        if not value.strip():
            _add_issue(timeline, "必须修复", str(scene.index), f"第 {scene.index} 格{label}为空")


def _review_scene_timing(timeline: Timeline, scene: Scene) -> None:
    if scene.start is None or scene.end is None or scene.duration is None:
        _add_issue(timeline, "必须修复", str(scene.index), f"第 {scene.index} 格时间格式无法解析：{scene.raw_time}")
        return
    if scene.duration <= 0:
        _add_issue(timeline, "必须修复", str(scene.index), f"第 {scene.index} 格时间倒序或时长为 0")


def _review_text_density(timeline: Timeline, scene: Scene) -> None:
    text_length = _compact_length(scene.onscreen_text)
    if text_length > 24:
        _add_issue(timeline, "建议修改", str(scene.index), f"第 {scene.index} 格屏幕大字偏长：{text_length} 字")

    if scene.duration and scene.duration > 0:
        voiceover_speed = _compact_length(scene.voiceover) / scene.duration
        if voiceover_speed > 7:
            _add_issue(timeline, "建议修改", str(scene.index), f"第 {scene.index} 格口播偏快：约 {voiceover_speed:.1f} 字/秒")


def _review_timing_sequence(timeline: Timeline) -> None:
    previous: Optional[Scene] = None
    for scene in timeline.scenes:
        if previous is None:
            previous = scene
            continue
        if (
            previous.end is None
            or scene.start is None
            or scene.end is None
        ):
            previous = scene
            continue
        if scene.start < previous.end - 0.01:
            _add_issue(
                timeline,
                "必须修复",
                str(scene.index),
                f"第 {scene.index} 格与第 {previous.index} 格时间重叠：{previous.raw_time} / {scene.raw_time}",
            )
        elif scene.start > previous.end + 0.05:
            gap = scene.start - previous.end
            _add_issue(
                timeline,
                "建议修改",
                str(scene.index),
                f"第 {scene.index} 格前有 {gap:.1f} 秒空档：{previous.raw_time} / {scene.raw_time}",
            )
        previous = scene


def _review_total_duration(timeline: Timeline) -> None:
    total = timeline.total_duration
    if total > 59:
        _add_issue(timeline, "建议修改", "-", f"总时长 {total:.1f} 秒，超过 59 秒目标")
    elif total > 58.5:
        _add_issue(timeline, "仅供参考", "-", f"总时长 {total:.1f} 秒，接近 59 秒边界")


def _review_keyword_coverage(timeline: Timeline) -> None:
    haystack = "\n".join(
        " ".join(
            [
                scene.voiceover,
                scene.onscreen_text,
                scene.visual,
                scene.edit_action,
                scene.sound,
                scene.effect,
            ]
        )
        for scene in timeline.scenes
    )
    checks = [
        ("开头结果或动画钩子", ("动画", "结果")),
        ("纸偶来源", ("纸偶",)),
        ("三步方法", ("第一步", "第二步", "第三步")),
        ("AI 价值观", ("AI 不是替代", "不是替代创作")),
        ("结尾收束", ("自己的故事", "属于自己的故事")),
    ]
    for label, keywords in checks:
        if not any(keyword in haystack for keyword in keywords):
            _add_issue(timeline, "仅供参考", "-", f"未明显覆盖关键内容：{label}")


def _compact_length(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def _add_issue(timeline: Timeline, severity: str, scene: str, message: str) -> None:
    issue = {"severity": severity, "scene": scene, "message": message}
    timeline.issues.append(issue)
    if scene.isdigit():
        scene_index = int(scene)
        for timeline_scene in timeline.scenes:
            if timeline_scene.index == scene_index:
                timeline_scene.issues.append(message)
                break


def _guess_asset_type(scene: Scene) -> str:
    text = " ".join([scene.visual, scene.edit_action, scene.onscreen_text])
    guesses = []
    checks = [
        ("AI 动画", ("AI", "动画", "故事世界")),
        ("纸偶/手工作品", ("纸偶", "手作", "角色零件", "作品")),
        ("绘本/画面截图", ("绘本", "花朵", "森林", "画纸", "场景")),
        ("人物展示", ("孩子", "老师", "展示")),
    ]
    for label, keywords in checks:
        if any(keyword in text for keyword in keywords):
            guesses.append(label)
    return "、".join(guesses) if guesses else "按画面描述人工准备"


def _render_issue_summary(timeline: Timeline) -> str:
    counts = {
        severity: len([issue for issue in timeline.issues if issue["severity"] == severity])
        for severity in ("必须修复", "建议修改", "仅供参考")
    }
    items = "".join(
        f"<div><strong>{escape(severity)}</strong><br>{count} 条</div>"
        for severity, count in counts.items()
    )
    return f'<section class="summary">{items}</section>'


def _render_toolbar() -> str:
    return """
<section class="toolbar">
  <input id="sceneSearch" class="search" type="search" placeholder="搜索分镜" autocomplete="off">
  <div class="segmented" aria-label="筛选">
    <button type="button" data-filter="all" aria-pressed="true">全部</button>
    <button type="button" data-filter="issues" aria-pressed="false">有问题</button>
    <button type="button" data-filter="unreviewed" aria-pressed="false">未审</button>
  </div>
  <div class="toolbar-actions">
    <input id="browserAssetDir" type="file" accept="image/*,video/*" webkitdirectory directory multiple hidden>
    <button type="button" id="chooseAssetDir">选择资料库</button>
    <span id="browserAssetStatus" class="browser-asset-status">未选择资料库</span>
    <button type="button" id="expandAll">展开</button>
    <button type="button" id="collapseAll">收起</button>
    <button type="button" id="clearReviewed">清空已审</button>
    <button type="button" id="resetOrder">恢复顺序</button>
    <button type="button" id="exportEdits">导出修改</button>
    <button type="button" id="resetEdits">重置修改</button>
  </div>
</section>
"""


def _render_timeline_panel(timeline: Timeline) -> str:
    return f"""<section id="timelinePanel" class="timeline-panel" aria-label="时间线">
  <div class="timeline-header">
    <div class="timeline-title">时间线</div>
    <div class="timeline-readout">
      <span>播放头 <strong id="playheadTime">00:00.0</strong></span>
      <span id="timelineDuration">总长 {timeline.total_duration:.1f}s</span>
    </div>
    <label class="timeline-zoom" for="timelineZoom">缩放
      <input id="timelineZoom" type="range" min="36" max="180" value="86">
    </label>
  </div>
  <div id="timelineViewport" class="timeline-viewport" title="滚轮缩放，按住空白处拖拽平移，拖动播放头定位">
    <div id="timelineCanvas" class="timeline-canvas">
      <div id="timelineRuler" class="timeline-ruler"></div>
      <div id="timelineTracks" class="timeline-tracks">
        <div class="timeline-track" data-track="video">
          <div class="timeline-track-label">V1</div>
          <div id="timelineVideoTrack" class="timeline-lane"></div>
        </div>
        <div class="timeline-track" data-track="audio">
          <div class="timeline-track-label">A1</div>
          <div id="timelineAudioTrack" class="timeline-lane"></div>
        </div>
        <div class="timeline-track" data-track="effect">
          <div class="timeline-track-label">FX</div>
          <div id="timelineEffectTrack" class="timeline-lane"></div>
        </div>
      </div>
      <div id="timelinePlayhead" class="timeline-playhead"></div>
    </div>
  </div>
</section>
"""


def _render_scene_card(
    scene: Scene,
    asset: Optional[SceneAsset],
    out_dir: Optional[Path],
    source_file: str,
    asset_dirs: Optional[Sequence[Path]] = None,
) -> str:
    issues = ""
    if scene.issues:
        issue_items = "".join(f"<li>{escape(issue)}</li>" for issue in scene.issues)
        issues = f'<div class="issues"><strong>审查提示</strong><ul>{issue_items}</ul></div>'
    card_class = "card has-issues" if scene.issues else "card"
    search_text = " ".join(
        [
            str(scene.index),
            scene.raw_time,
            scene.voiceover,
            scene.onscreen_text,
            scene.visual,
            scene.edit_action,
            scene.sound,
            scene.effect,
            " ".join(scene.issues),
            asset.path.name if asset else "",
        ]
    )
    matched_asset = str(asset.path) if asset else "未匹配"
    start = "" if scene.start is None else f"{scene.start:.3f}"
    end = "" if scene.end is None else f"{scene.end:.3f}"
    duration = "" if scene.duration is None else f"{scene.duration:.3f}"
    asset_text = "\n".join(
        [
            f"第 {scene.index} 格 {scene.raw_time}",
            f"素材：{matched_asset}",
            f"画面：{scene.visual or '空'}",
            f"剪辑：{scene.edit_action or '空'}",
            f"音效：{scene.sound or '空'}",
            f"特效：{scene.effect or '空'}",
        ]
    )
    return f"""
<article id="scene-{scene.index}" class="{card_class}" tabindex="-1" data-scene-card data-index="{scene.index}" data-time="{_html_attr(scene.raw_time)}" data-start="{start}" data-end="{end}" data-duration="{duration}" data-asset="{_html_attr(matched_asset)}" data-visual="{_html_attr(scene.visual)}" data-has-issues="{1 if scene.issues else 0}" data-search="{_html_attr(search_text)}">
  {_render_scene_frame(scene, asset, out_dir)}
  <section class="body">
    <div class="scene-actions">
      <div class="scene-actions-left">
        <button type="button" class="drag-handle" draggable="true" data-drag-handle aria-label="拖动第 {scene.index} 格调整顺序" title="拖动排序">拖动排序</button>
        <button type="button" data-action="toggle-details" aria-expanded="true">收起</button>
      </div>
      <div class="scene-actions-right">
        <button type="button" data-action="copy-voiceover" data-copy="{_html_attr(scene.voiceover)}">复制口播</button>
        <button type="button" data-action="copy-assets" data-copy="{_html_attr(asset_text)}">复制素材</button>
      </div>
    </div>
    <div class="details">
      {_render_field("匹配素材", matched_asset)}
      {_render_video_clip_tool(scene, source_file, out_dir, asset_dirs)}
      {_render_editable_field(scene, "口播", "voiceover", scene.voiceover)}
      {_render_editable_field(scene, "剪辑动作", "edit_action", scene.edit_action)}
      {_render_editable_field(scene, "音效 / BGM", "sound", scene.sound)}
      {_render_editable_field(scene, "画面特效 / 转场", "effect", scene.effect)}
      {issues}
    </div>
  </section>
</article>
"""


def _render_scene_frame(scene: Scene, asset: Optional[SceneAsset], out_dir: Optional[Path]) -> str:
    media = ""
    asset_label = ""
    frame_class = "frame"
    if asset:
        frame_class = "frame has-media"
        asset_url = _asset_url(asset.path, out_dir)
        label = f"素材：{asset.path.name}"
        asset_label = f'<div class="asset-label">{escape(label)}</div>'
        if asset.kind == "image":
            media = f'<img class="scene-media" src="{_html_attr(asset_url)}" alt="第 {scene.index} 格素材：{_html_attr(asset.path.name)}">'
        else:
            media = f'<video class="scene-media" src="{_html_attr(asset_url)}" muted controls playsinline preload="metadata"></video>'

    return f"""
<section class="{frame_class}">
  {media}
  <div class="frame-content">
    <div class="frame-top">
      <div class="time">第 {scene.index} 格 · {escape(scene.raw_time)}</div>
      <label class="review-control">
        <input class="review-toggle" type="checkbox" data-index="{scene.index}">
        已审
      </label>
    </div>
    <div>
      <div class="bigtext">{escape(scene.onscreen_text or "屏幕大字为空")}</div>
      {asset_label}
    </div>
    <div class="visual">{escape(scene.visual or "画面内容为空")}</div>
  </div>
</section>
"""


def _render_interaction_script() -> str:
    return """
<script>
(() => {
  const sceneGrid = document.getElementById("sceneGrid");
  let cards = Array.from(document.querySelectorAll("[data-scene-card]"));
  const search = document.getElementById("sceneSearch");
  const filterButtons = Array.from(document.querySelectorAll("[data-filter]"));
  const emptyState = document.getElementById("emptyState");
  const toast = document.getElementById("toast");
  const soundPreviewPanel = document.getElementById("soundPreviewPanel");
  const pendingPresetLabel = document.getElementById("pendingPresetLabel");
  const pendingSceneLabel = document.getElementById("pendingSceneLabel");
  const browserAssetInput = document.getElementById("browserAssetDir");
  const browserAssetStatus = document.getElementById("browserAssetStatus");
  const timelinePanel = document.getElementById("timelinePanel");
  const timelineViewport = document.getElementById("timelineViewport");
  const timelineCanvas = document.getElementById("timelineCanvas");
  const timelineRuler = document.getElementById("timelineRuler");
  const timelineVideoTrack = document.getElementById("timelineVideoTrack");
  const timelineAudioTrack = document.getElementById("timelineAudioTrack");
  const timelineEffectTrack = document.getElementById("timelineEffectTrack");
  const timelinePlayhead = document.getElementById("timelinePlayhead");
  const timelineZoom = document.getElementById("timelineZoom");
  const playheadTime = document.getElementById("playheadTime");
  const timelineDuration = document.getElementById("timelineDuration");
  const storageKey = "storyboard-reviewed:" + (document.body.dataset.source || location.pathname);
  const editsStorageKey = "storyboard-edits:" + (document.body.dataset.source || location.pathname);
  const orderStorageKey = "storyboard-order:" + (document.body.dataset.source || location.pathname);
  const imageExtensions = new Set(["jpg", "jpeg", "png", "webp", "gif"]);
  const videoExtensions = new Set(["mp4", "mov", "m4v", "webm"]);
  let activeIndex = 0;
  let currentFilter = "all";
  let toastTimer = 0;
  let pendingPreset = null;
  let audioContext = null;
  let draggedCard = null;
  let browserAssets = [];
  let currentPlayheadSeconds = 0;
  let timelineDrag = null;
  let suppressTimelineClick = false;
  const timelineLabelWidth = 52;

  function loadReviewed() {
    try {
      return new Set(JSON.parse(localStorage.getItem(storageKey) || "[]"));
    } catch (error) {
      return new Set();
    }
  }

  function saveReviewed(reviewed) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(Array.from(reviewed)));
    } catch (error) {
      showToast("状态未保存");
    }
  }

  function loadEdits() {
    try {
      return JSON.parse(localStorage.getItem(editsStorageKey) || "{}");
    } catch (error) {
      return {};
    }
  }

  function saveEdits(edits) {
    try {
      localStorage.setItem(editsStorageKey, JSON.stringify(edits));
    } catch (error) {
      showToast("修改未保存");
    }
  }

  function loadOrder() {
    try {
      const order = JSON.parse(localStorage.getItem(orderStorageKey) || "[]");
      return Array.isArray(order) ? order.map(String) : [];
    } catch (error) {
      return [];
    }
  }

  function saveOrder() {
    try {
      localStorage.setItem(orderStorageKey, JSON.stringify(cards.map((card) => card.dataset.index)));
    } catch (error) {
      showToast("顺序未保存");
    }
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("is-visible");
    toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 1300);
  }

  function formatTimelineTime(seconds) {
    const safeSeconds = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
    const tenthsTotal = Math.round(safeSeconds * 10);
    const minutes = Math.floor(tenthsTotal / 600);
    const second = Math.floor((tenthsTotal % 600) / 10);
    const tenth = tenthsTotal % 10;
    return `${String(minutes).padStart(2, "0")}:${String(second).padStart(2, "0")}.${tenth}`;
  }

  function parseTimelineNumber(value) {
    const number = Number.parseFloat(value || "");
    return Number.isFinite(number) ? number : Number.NaN;
  }

  function timelinePxPerSecond() {
    const value = Number.parseFloat(timelineZoom ? timelineZoom.value : "");
    return Number.isFinite(value) ? value : 86;
  }

  function clampTimelineZoom(value) {
    if (!timelineZoom) return 86;
    const min = Number.parseFloat(timelineZoom.min || "36");
    const max = Number.parseFloat(timelineZoom.max || "180");
    const number = Number.parseFloat(value);
    if (!Number.isFinite(number)) return timelinePxPerSecond();
    return Math.min(max, Math.max(min, Math.round(number)));
  }

  function setTimelineZoom(value, anchorSeconds) {
    if (!timelineZoom) return;
    const previousPxPerSecond = timelinePxPerSecond();
    const anchorOffset = timelineViewport && Number.isFinite(anchorSeconds)
      ? timelineLabelWidth + anchorSeconds * previousPxPerSecond - timelineViewport.scrollLeft
      : null;
    timelineZoom.value = String(clampTimelineZoom(value));
    renderTimeline();
    if (timelineViewport && anchorOffset !== null) {
      const nextScrollLeft = timelineLabelWidth + anchorSeconds * timelinePxPerSecond() - anchorOffset;
      timelineViewport.scrollLeft = Math.max(0, nextScrollLeft);
    }
    setTimelinePlayhead(currentPlayheadSeconds);
  }

  function zoomTimelineAt(deltaY, anchorSeconds) {
    const factor = deltaY < 0 ? 1.14 : 0.88;
    setTimelineZoom(timelinePxPerSecond() * factor, anchorSeconds);
  }

  function timelineTrackText(card, track) {
    if (track === "video") {
      const asset = card.dataset.asset || "";
      if (asset && asset !== "未匹配") return asset.split(/[\\/]/).pop();
      return card.dataset.visual || "画面素材";
    }
    if (track === "audio") {
      return [fieldValue(card, "voiceover"), fieldValue(card, "sound")]
        .filter(Boolean)
        .join(" / ") || "口播 / 音效";
    }
    return [fieldValue(card, "edit_action"), fieldValue(card, "effect")]
      .filter(Boolean)
      .join(" / ") || "剪辑 / 特效";
  }

  function timelineClipData() {
    let cursor = 0;
    return cards
      .map((card) => {
        let start = parseTimelineNumber(card.dataset.start);
        let duration = parseTimelineNumber(card.dataset.duration);
        let end = parseTimelineNumber(card.dataset.end);
        if (!Number.isFinite(duration) || duration <= 0) duration = 3;
        if (!Number.isFinite(start)) start = cursor;
        if (!Number.isFinite(end) || end <= start) end = start + duration;
        duration = Math.max(0.1, end - start);
        cursor = Math.max(cursor, end);
        return {
          card,
          index: Number(card.dataset.index),
          start,
          end,
          duration
        };
      })
      .sort((first, second) => first.start - second.start || first.index - second.index);
  }

  function timelineTotalSeconds(items) {
    return items.reduce((total, item) => Math.max(total, item.end), 0);
  }

  function timelineTickStep(total) {
    if (total <= 18) return 1;
    if (total <= 45) return 2;
    if (total <= 90) return 5;
    return 10;
  }

  function clearElement(element) {
    while (element && element.firstChild) element.removeChild(element.firstChild);
  }

  function createTimelineClip(item, track, label) {
    const clip = document.createElement("button");
    clip.type = "button";
    clip.className = `timeline-clip timeline-clip-${track}`;
    clip.setAttribute("data-timeline-clip", "1");
    clip.dataset.index = String(item.index);
    clip.dataset.track = track;
    clip.title = `第 ${item.index} 格 ${formatTimelineTime(item.start)}-${formatTimelineTime(item.end)} · ${label}`;
    clip.style.left = `${item.start * timelinePxPerSecond()}px`;
    clip.style.width = `${Math.max(22, item.duration * timelinePxPerSecond() - 3)}px`;

    const index = document.createElement("span");
    index.className = "timeline-clip-index";
    index.textContent = String(item.index);
    const text = document.createElement("span");
    text.className = "timeline-clip-label";
    text.textContent = label;
    clip.appendChild(index);
    clip.appendChild(text);
    clip.addEventListener("click", (event) => {
      event.stopPropagation();
      selectTimelineScene(item, item.start);
    });
    return clip;
  }

  function renderTimeline() {
    if (!timelinePanel || !timelineViewport || !timelineCanvas) return;
    const items = timelineClipData();
    const total = Math.max(1, timelineTotalSeconds(items));
    const pxPerSecond = timelinePxPerSecond();
    const laneWidth = Math.max(320, Math.ceil(total * pxPerSecond) + 24);
    const canvasWidth = Math.max(timelineViewport.clientWidth || 0, timelineLabelWidth + laneWidth);
    timelineCanvas.style.width = `${canvasWidth}px`;

    [timelineRuler, timelineVideoTrack, timelineAudioTrack, timelineEffectTrack].forEach((element) => {
      if (!element) return;
      clearElement(element);
      element.style.width = `${canvasWidth - timelineLabelWidth}px`;
      if (element.classList.contains("timeline-lane")) {
        element.style.backgroundSize = `${pxPerSecond}px 100%`;
      }
    });

    if (timelineDuration) timelineDuration.textContent = `总长 ${formatTimelineTime(total)}`;
    const step = timelineTickStep(total);
    for (let seconds = 0; seconds <= total + 0.001; seconds += step) {
      const tick = document.createElement("div");
      tick.className = "timeline-tick";
      tick.style.left = `${seconds * pxPerSecond}px`;
      const label = document.createElement("span");
      label.textContent = formatTimelineTime(seconds);
      tick.appendChild(label);
      if (timelineRuler) timelineRuler.appendChild(tick);
    }

    items.forEach((item) => {
      timelineVideoTrack.appendChild(createTimelineClip(item, "video", timelineTrackText(item.card, "video")));
      timelineAudioTrack.appendChild(createTimelineClip(item, "audio", timelineTrackText(item.card, "audio")));
      timelineEffectTrack.appendChild(createTimelineClip(item, "effect", timelineTrackText(item.card, "effect")));
    });
    updateTimelineActive(cards[activeIndex]);
    setTimelinePlayhead(currentPlayheadSeconds);
  }

  function setTimelinePlayhead(seconds) {
    if (!timelinePlayhead) return;
    const items = timelineClipData();
    const total = Math.max(timelineTotalSeconds(items), seconds || 0, 0);
    const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.min(seconds, total)) : 0;
    currentPlayheadSeconds = safeSeconds;
    timelinePlayhead.style.left = `${timelineLabelWidth + safeSeconds * timelinePxPerSecond()}px`;
    if (playheadTime) playheadTime.textContent = formatTimelineTime(safeSeconds);
  }

  function updateTimelineActive(card) {
    if (!timelinePanel) return;
    const index = card ? card.dataset.index : "";
    timelinePanel.querySelectorAll("[data-timeline-clip]").forEach((clip) => {
      clip.classList.toggle("is-active", clip.dataset.index === index);
    });
  }

  function sceneFromTimelinePoint(seconds) {
    const items = timelineClipData();
    const direct = items.find((item) => seconds >= item.start && seconds <= item.end);
    if (direct) return direct;
    return items.reduce((nearest, item) => {
      if (!nearest) return item;
      const nearestDistance = Math.min(Math.abs(seconds - nearest.start), Math.abs(seconds - nearest.end));
      const itemDistance = Math.min(Math.abs(seconds - item.start), Math.abs(seconds - item.end));
      return itemDistance < nearestDistance ? item : nearest;
    }, null);
  }

  function timelineSecondsFromEvent(event) {
    if (!timelineViewport) return 0;
    const rect = timelineViewport.getBoundingClientRect();
    const x = event.clientX - rect.left + timelineViewport.scrollLeft - timelineLabelWidth;
    return Math.max(0, x / timelinePxPerSecond());
  }

  function selectTimelineScene(item, seconds) {
    if (!item || !item.card) return;
    setActiveCard(item.card, { syncPlayhead: false });
    setTimelinePlayhead(Number.isFinite(seconds) ? seconds : item.start);
    item.card.scrollIntoView({ behavior: "smooth", block: "center" });
    item.card.focus({ preventScroll: true });
  }

  function beginTimelinePan(event) {
    if (!timelineViewport || event.button !== 0) return;
    if (event.target.closest("[data-timeline-clip]") || event.target.closest("button, input, label")) return;
    if (timelinePlayhead && timelinePlayhead.contains(event.target)) return;
    timelineDrag = {
      mode: "pan",
      pointerId: event.pointerId,
      startX: event.clientX,
      startScrollLeft: timelineViewport.scrollLeft,
      moved: false,
      target: timelineViewport
    };
    timelineViewport.classList.add("is-dragging");
    if (timelineViewport.setPointerCapture) timelineViewport.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function beginPlayheadDrag(event) {
    if (!timelinePlayhead || event.button !== 0) return;
    timelineDrag = {
      mode: "playhead",
      pointerId: event.pointerId,
      moved: true,
      target: timelinePlayhead
    };
    if (timelinePlayhead.setPointerCapture) timelinePlayhead.setPointerCapture(event.pointerId);
    event.preventDefault();
    event.stopPropagation();
    handleTimelinePointerMove(event);
  }

  function handleTimelinePointerMove(event) {
    if (!timelineDrag || timelineDrag.pointerId !== event.pointerId) return;
    if (timelineDrag.mode === "pan") {
      const deltaX = event.clientX - timelineDrag.startX;
      if (Math.abs(deltaX) > 2) {
        timelineDrag.moved = true;
        suppressTimelineClick = true;
      }
      timelineViewport.scrollLeft = Math.max(0, timelineDrag.startScrollLeft - deltaX);
      event.preventDefault();
      return;
    }
    if (timelineDrag.mode === "playhead") {
      const seconds = timelineSecondsFromEvent(event);
      const item = sceneFromTimelinePoint(seconds);
      setTimelinePlayhead(seconds);
      updateTimelineActive(item ? item.card : null);
      event.preventDefault();
    }
  }

  function endTimelinePointerDrag(event) {
    if (!timelineDrag || (event && timelineDrag.pointerId !== event.pointerId)) return;
    const finishedDrag = timelineDrag;
    timelineDrag = null;
    if (timelineViewport) timelineViewport.classList.remove("is-dragging");
    if (finishedDrag.target && finishedDrag.target.releasePointerCapture) {
      try {
        finishedDrag.target.releasePointerCapture(finishedDrag.pointerId);
      } catch (error) {
        // Pointer capture may already be released by the browser.
      }
    }
    if (finishedDrag.mode === "playhead") {
      const item = sceneFromTimelinePoint(currentPlayheadSeconds);
      if (item) setActiveCard(item.card, { syncPlayhead: false });
      setTimelinePlayhead(currentPlayheadSeconds);
    }
    if (finishedDrag.mode === "pan" && finishedDrag.moved) {
      window.setTimeout(() => {
        suppressTimelineClick = false;
      }, 0);
    } else {
      suppressTimelineClick = false;
    }
  }

  function syncCardsFromDom() {
    const activeCard = cards[activeIndex] || null;
    cards = Array.from(sceneGrid.querySelectorAll("[data-scene-card]"));
    activeIndex = activeCard ? cards.indexOf(activeCard) : activeIndex;
    if (activeIndex < 0) activeIndex = 0;
  }

  function applySavedOrder() {
    const order = loadOrder();
    if (!order.length) return;
    const byIndex = new Map(cards.map((card) => [card.dataset.index, card]));
    order.forEach((index) => {
      const card = byIndex.get(index);
      if (card) sceneGrid.appendChild(card);
    });
    cards.forEach((card) => {
      if (!order.includes(card.dataset.index)) sceneGrid.appendChild(card);
    });
    syncCardsFromDom();
  }

  function assetKind(file) {
    const extension = (file.name.split(".").pop() || "").toLowerCase();
    if (imageExtensions.has(extension)) return "image";
    if (videoExtensions.has(extension)) return "video";
    return "";
  }

  function assetSceneIndex(asset) {
    const path = (asset.relativePath || asset.file.name).toLowerCase();
    const name = asset.file.name.toLowerCase();
    const patterns = [
      /(?:^|\\/)(\\d{1,2})[_\\-.]/,
      /(?:^|\\/)scene[_-]?(\\d{1,2})/,
      /第\\s*(\\d{1,2})\\s*格/
    ];
    for (const pattern of patterns) {
      const match = path.match(pattern) || name.match(pattern);
      if (match) return Number(match[1]);
    }
    return 0;
  }

  function assetSortValue(asset) {
    const kindRank = asset.kind === "video" ? 0 : 1;
    const clipRank = asset.file.name.toLowerCase().includes("clip") ? 0 : 1;
    return `${kindRank}:${clipRank}:${asset.relativePath.toLowerCase()}`;
  }

  function browserAssetLabel(asset) {
    return asset.relativePath || asset.file.name;
  }

  function setCardMedia(card, asset) {
    const frame = card.querySelector(".frame");
    const frameContent = frame ? frame.querySelector(".frame-content") : null;
    if (!frame || !frameContent) return;
    const existingMedia = frame.querySelector(".scene-media");
    if (existingMedia) existingMedia.remove();

    const media = document.createElement(asset.kind === "video" ? "video" : "img");
    media.className = "scene-media";
    media.src = asset.url;
    if (asset.kind === "video") {
      media.muted = true;
      media.controls = true;
      media.playsInline = true;
      media.preload = "metadata";
    } else {
      media.alt = `第 ${card.dataset.index} 格素材：${asset.file.name}`;
    }
    frame.insertBefore(media, frameContent);
    frame.classList.add("has-media");

    let label = frame.querySelector(".asset-label");
    if (!label) {
      label = document.createElement("div");
      label.className = "asset-label";
      const bigText = frameContent.querySelector(".bigtext");
      if (bigText && bigText.parentElement) bigText.parentElement.appendChild(label);
    }
    label.textContent = `素材：${asset.file.name}`;
    card.dataset.asset = browserAssetLabel(asset);
    const matched = card.querySelector("[data-matched-asset]");
    if (matched) matched.textContent = browserAssetLabel(asset);
  }

  function updateClipSourceOptions(videoAssets) {
    cards.forEach((card) => {
      const select = card.querySelector("[data-video-source]");
      if (!select) return;
      select.querySelectorAll("[data-browser-asset]").forEach((option) => option.remove());
      if (videoAssets.length) {
        const heading = document.createElement("option");
        heading.disabled = true;
        heading.dataset.browserAsset = "1";
        heading.textContent = "浏览器选择的资料库";
        select.appendChild(heading);
      }
      videoAssets.forEach((asset) => {
        const option = document.createElement("option");
        option.value = asset.url;
        option.dataset.browserAsset = "1";
        option.dataset.browserPath = browserAssetLabel(asset);
        option.textContent = browserAssetLabel(asset);
        select.appendChild(option);
      });
      updateClipPreview(card, "in");
    });
  }

  function applyBrowserAssets(fileList) {
    browserAssets.forEach((asset) => URL.revokeObjectURL(asset.url));
    browserAssets = Array.from(fileList)
      .map((file) => ({
        file,
        kind: assetKind(file),
        relativePath: file.webkitRelativePath || file.name,
        url: URL.createObjectURL(file)
      }))
      .filter((asset) => asset.kind);
    browserAssets.sort((first, second) => assetSortValue(first).localeCompare(assetSortValue(second)));

    const videoAssets = browserAssets.filter((asset) => asset.kind === "video");
    updateClipSourceOptions(videoAssets);
    cards.forEach((card) => {
      const sceneIndex = Number(card.dataset.index);
      const matched = browserAssets.find((asset) => assetSceneIndex(asset) === sceneIndex);
      if (matched) setCardMedia(card, matched);
    });
    applyFilters();
    renderTimeline();
    if (browserAssetStatus) browserAssetStatus.textContent = `已载入 ${browserAssets.length} 个素材`;
    showToast(`已载入 ${browserAssets.length} 个素材`);
  }

  function applyReviewedState() {
    const reviewed = loadReviewed();
    cards.forEach((card) => {
      const checked = reviewed.has(card.dataset.index);
      card.classList.toggle("is-reviewed", checked);
      card.dataset.reviewed = checked ? "1" : "0";
      const checkbox = card.querySelector(".review-toggle");
      if (checkbox) checkbox.checked = checked;
    });
  }

  function applyEditState() {
    const edits = loadEdits();
    cards.forEach((card) => {
      const sceneEdits = edits[card.dataset.index] || {};
      let edited = false;
      card.querySelectorAll("[data-edit-field]").forEach((field) => {
        const value = Object.prototype.hasOwnProperty.call(sceneEdits, field.dataset.editField)
          ? sceneEdits[field.dataset.editField]
          : field.dataset.original || "";
        field.value = value;
        if (value !== (field.dataset.original || "")) edited = true;
      });
      card.classList.toggle("is-edited", edited);
      card.dataset.edited = edited ? "1" : "0";
    });
  }

  function saveField(field) {
    const card = field.closest("[data-scene-card]");
    const edits = loadEdits();
    const index = card.dataset.index;
    edits[index] = edits[index] || {};
    if (field.value === (field.dataset.original || "")) {
      delete edits[index][field.dataset.editField];
    } else {
      edits[index][field.dataset.editField] = field.value;
    }
    if (Object.keys(edits[index]).length === 0) delete edits[index];
    saveEdits(edits);
    applyEditState();
  }

  function fieldValue(card, fieldName) {
    const field = card.querySelector(`[data-edit-field="${fieldName}"]`);
    return field ? field.value : "";
  }

  function scenePayload(card, position) {
    return {
      position: position || cards.indexOf(card) + 1,
      index: Number(card.dataset.index),
      time: card.dataset.time || "",
      asset: card.dataset.asset || "",
      visual: card.dataset.visual || "",
      voiceover: fieldValue(card, "voiceover"),
      edit_action: fieldValue(card, "edit_action"),
      sound: fieldValue(card, "sound"),
      effect: fieldValue(card, "effect")
    };
  }

  function sceneText(card) {
    const scene = scenePayload(card);
    return [
      `第 ${scene.index} 格 ${scene.time}`,
      `素材：${scene.asset}`,
      `画面：${scene.visual}`,
      `口播：${scene.voiceover}`,
      `剪辑：${scene.edit_action}`,
      `音效：${scene.sound}`,
      `特效：${scene.effect}`
    ].join("\\n");
  }

  function exportEditedScenes() {
    return cards.map((card, index) => scenePayload(card, index + 1));
  }

  function getAudioContext() {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return null;
    if (!audioContext) audioContext = new Context();
    if (audioContext.state === "suspended") audioContext.resume();
    return audioContext;
  }

  function playTone(ctx, start, duration, frequency, endFrequency, type) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type || "sine";
    osc.frequency.setValueAtTime(frequency, start);
    if (endFrequency) osc.frequency.exponentialRampToValueAtTime(endFrequency, start + duration);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.22, start + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(gain).connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration + 0.02);
  }

  function playNoise(ctx, start, duration, highpass) {
    const sampleRate = ctx.sampleRate;
    const buffer = ctx.createBuffer(1, Math.max(1, Math.floor(sampleRate * duration)), sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i += 1) {
      data[i] = Math.random() * 2 - 1;
    }
    const source = ctx.createBufferSource();
    const filter = ctx.createBiquadFilter();
    const gain = ctx.createGain();
    filter.type = highpass ? "highpass" : "bandpass";
    filter.frequency.setValueAtTime(highpass ? 900 : 1400, start);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.18, start + 0.018);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    source.buffer = buffer;
    source.connect(filter).connect(gain).connect(ctx.destination);
    source.start(start);
    source.stop(start + duration);
  }

  function playPresetPreview(preset) {
    const ctx = getAudioContext();
    if (!ctx) {
      showToast("当前浏览器不能试听");
      return;
    }
    const start = ctx.currentTime + 0.02;
    if (preset.includes("BGM")) {
      [261.63, 329.63, 392.0, 523.25].forEach((frequency, offset) => {
        playTone(ctx, start + offset * 0.12, 0.28, frequency, null, "sine");
      });
      return;
    }
    if (preset.includes("whoosh") || preset.includes("reveal")) {
      playNoise(ctx, start, 0.36, false);
      playTone(ctx, start, 0.36, 180, 880, "sine");
      return;
    }
    if (preset.includes("pop")) {
      playTone(ctx, start, 0.16, 520, 110, "sine");
      return;
    }
    if (preset.includes("tap") || preset.includes("click") || preset.includes("低频")) {
      playTone(ctx, start, 0.08, preset.includes("低频") ? 95 : 900, preset.includes("低频") ? 55 : 420, "square");
      return;
    }
    if (preset.includes("纸张") || preset.includes("翻页")) {
      playNoise(ctx, start, 0.22, true);
      return;
    }
    if (preset.includes("shimmer")) {
      [740, 988, 1319].forEach((frequency, offset) => playTone(ctx, start + offset * 0.08, 0.22, frequency, null, "triangle"));
      return;
    }
    playTone(ctx, start, 0.18, 440, 660, "sine");
  }

  function previewPreset(card, preset) {
    pendingPreset = { card, preset };
    pendingPresetLabel.textContent = `已试听：${preset}`;
    pendingSceneLabel.textContent = `第 ${card.dataset.index} 格，确认后加入到音效 / BGM`;
    soundPreviewPanel.hidden = false;
    playPresetPreview(preset);
    showToast("已试听，确认后加入");
  }

  function appendPendingPreset() {
    if (!pendingPreset) return;
    const field = pendingPreset.card.querySelector('[data-edit-field="sound"]');
    const current = field.value.trim();
    field.value = current ? `${current}；${pendingPreset.preset}` : pendingPreset.preset;
    saveField(field);
    soundPreviewPanel.hidden = true;
    showToast("已加入音效");
    pendingPreset = null;
  }

  function shouldPlaceAfter(target, x, y) {
    const rect = target.getBoundingClientRect();
    const middleY = rect.top + rect.height / 2;
    const middleX = rect.left + rect.width / 2;
    const isSameRowGesture = Math.abs(y - middleY) < rect.height * 0.42;
    return isSameRowGesture ? x > middleX : y > middleY;
  }

  function clearDropTargets() {
    cards.forEach((card) => card.classList.remove("is-drop-target"));
  }

  function finishDragSort() {
    if (!draggedCard) return;
    const movedCard = draggedCard;
    movedCard.classList.remove("is-dragging");
    clearDropTargets();
    syncCardsFromDom();
    saveOrder();
    applyFilters();
    setActiveCard(movedCard);
    showToast("顺序已保存");
    draggedCard = null;
  }

  function resetOrder() {
    try {
      localStorage.removeItem(orderStorageKey);
    } catch (error) {
      showToast("顺序未重置");
    }
    cards
      .slice()
      .sort((first, second) => Number(first.dataset.index) - Number(second.dataset.index))
      .forEach((card) => sceneGrid.appendChild(card));
    syncCardsFromDom();
    applyFilters();
    if (cards[0]) setActiveCard(cards[0]);
    showToast("已恢复原顺序");
  }

  function visibleCards() {
    return cards.filter((card) => !card.classList.contains("is-hidden"));
  }

  function applyFilters() {
    const term = (search.value || "").trim().toLowerCase();
    let visibleCount = 0;
    cards.forEach((card) => {
      const matchesSearch = !term || (card.dataset.search || "").toLowerCase().includes(term);
      const matchesFilter =
        currentFilter === "all" ||
        (currentFilter === "issues" && card.dataset.hasIssues === "1") ||
        (currentFilter === "unreviewed" && card.dataset.reviewed !== "1");
      const isVisible = matchesSearch && matchesFilter;
      card.classList.toggle("is-hidden", !isVisible);
      if (isVisible) visibleCount += 1;
    });
    emptyState.classList.toggle("is-visible", visibleCount === 0);
    if (visibleCount > 0 && !visibleCards().includes(cards[activeIndex])) {
      setActiveCard(visibleCards()[0]);
    }
  }

  function setActiveCard(card, options) {
    if (!card) return;
    cards.forEach((item) => item.classList.remove("is-active"));
    card.classList.add("is-active");
    activeIndex = cards.indexOf(card);
    updateTimelineActive(card);
    const start = parseTimelineNumber(card.dataset.start);
    const shouldSyncPlayhead = !options || options.syncPlayhead !== false;
    if (shouldSyncPlayhead && Number.isFinite(start)) setTimelinePlayhead(start);
  }

  function scrollScene(direction) {
    const list = visibleCards();
    if (!list.length) return;
    const current = cards[activeIndex];
    const currentVisibleIndex = Math.max(0, list.indexOf(current));
    const nextVisibleIndex = Math.min(list.length - 1, Math.max(0, currentVisibleIndex + direction));
    const next = list[nextVisibleIndex];
    setActiveCard(next);
    next.scrollIntoView({ behavior: "smooth", block: "center" });
    next.focus({ preventScroll: true });
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const input = document.createElement("textarea");
    input.value = text;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.left = "-999px";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    document.body.removeChild(input);
  }

  function clipElements(card) {
    return {
      select: card.querySelector("[data-video-source]"),
      preview: card.querySelector("[data-clip-preview]"),
      empty: card.querySelector("[data-clip-preview-empty]"),
      slider: card.querySelector("[data-clip-slider]"),
      inRange: card.querySelector("[data-clip-in]"),
      outRange: card.querySelector("[data-clip-out]"),
      inOutput: card.querySelector("[data-clip-in-output]"),
      outOutput: card.querySelector("[data-clip-out-output]")
    };
  }

  function clipRangeNumber(input, fallback) {
    const value = input ? Number.parseFloat(input.value) : Number.NaN;
    return Number.isFinite(value) ? value : fallback;
  }

  function formatClipSeconds(seconds) {
    return `${Math.max(0, seconds).toFixed(1)}s`;
  }

  function syncClipRange(card, changedHandle) {
    const clip = clipElements(card);
    if (!clip.inRange || !clip.outRange) return { inPoint: 0, outPoint: 0, max: 0 };
    const step = Number.parseFloat(clip.inRange.step || clip.outRange.step || "0.1") || 0.1;
    const max = Math.max(step, Number.parseFloat(clip.outRange.max || clip.inRange.max || "3") || 3);
    let inPoint = Math.min(max, Math.max(0, clipRangeNumber(clip.inRange, 0)));
    let outPoint = Math.min(max, Math.max(0, clipRangeNumber(clip.outRange, max)));

    if (changedHandle === "in" && inPoint > outPoint - step) inPoint = Math.max(0, outPoint - step);
    if (changedHandle === "out" && outPoint < inPoint + step) outPoint = Math.min(max, inPoint + step);
    if (outPoint <= inPoint) outPoint = Math.min(max, inPoint + step);
    if (outPoint > max) outPoint = max;
    if (inPoint >= outPoint) inPoint = Math.max(0, outPoint - step);

    clip.inRange.value = inPoint.toFixed(1);
    clip.outRange.value = outPoint.toFixed(1);
    if (clip.inOutput) clip.inOutput.textContent = formatClipSeconds(inPoint);
    if (clip.outOutput) clip.outOutput.textContent = formatClipSeconds(outPoint);
    if (clip.slider) {
      clip.slider.style.setProperty("--clip-in-percent", `${(inPoint / max) * 100}%`);
      clip.slider.style.setProperty("--clip-out-percent", `${(outPoint / max) * 100}%`);
    }
    return { inPoint, outPoint, max };
  }

  function setClipRangeMax(card, duration) {
    if (!Number.isFinite(duration) || duration <= 0) return;
    const clip = clipElements(card);
    if (!clip.inRange || !clip.outRange) return;
    const max = Math.max(0.1, duration);
    clip.inRange.max = max.toFixed(1);
    clip.outRange.max = max.toFixed(1);
    if (clipRangeNumber(clip.outRange, 0) > max) clip.outRange.value = max.toFixed(1);
    syncClipRange(card);
  }

  function seekClipPreview(card, handle) {
    const clip = clipElements(card);
    if (!clip.preview || !clip.preview.src) return;
    const range = syncClipRange(card, handle);
    const target = handle === "out" ? range.outPoint : range.inPoint;
    try {
      const max = Number.isFinite(clip.preview.duration) ? clip.preview.duration : target;
      clip.preview.currentTime = Math.min(Math.max(0, target), max);
    } catch (error) {
      // Some browsers reject currentTime changes before metadata is ready.
    }
  }

  function updateClipPreview(card, handle) {
    const clip = clipElements(card);
    if (!clip.select || !clip.preview) {
      syncClipRange(card, handle);
      return;
    }
    const option = clip.select.selectedOptions && clip.select.selectedOptions[0];
    const source = option && option.value ? option.value : "";
    if (!source) {
      clip.preview.removeAttribute("src");
      clip.preview.removeAttribute("data-current-source");
      clip.preview.load();
      if (clip.empty) clip.empty.hidden = false;
      syncClipRange(card, handle);
      return;
    }
    if (clip.preview.dataset.currentSource !== source) {
      clip.preview.dataset.currentSource = source;
      clip.preview.src = source;
      clip.preview.load();
    }
    if (clip.empty) clip.empty.hidden = true;
    seekClipPreview(card, handle || "in");
  }

  filterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      currentFilter = button.dataset.filter;
      filterButtons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
      applyFilters();
    });
  });

  search.addEventListener("input", applyFilters);
  document.getElementById("chooseAssetDir").addEventListener("click", () => browserAssetInput.click());
  browserAssetInput.addEventListener("change", () => {
    applyBrowserAssets(browserAssetInput.files || []);
  });
  if (timelineZoom) {
    timelineZoom.addEventListener("input", () => setTimelineZoom(timelineZoom.value, currentPlayheadSeconds));
  }
  if (timelinePlayhead) {
    timelinePlayhead.addEventListener("pointerdown", beginPlayheadDrag);
  }
  if (timelineViewport) {
    timelineViewport.addEventListener("wheel", (event) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      event.preventDefault();
      zoomTimelineAt(event.deltaY, timelineSecondsFromEvent(event));
    }, { passive: false });
    timelineViewport.addEventListener("pointerdown", beginTimelinePan);
    timelineViewport.addEventListener("pointermove", handleTimelinePointerMove);
    timelineViewport.addEventListener("pointerup", endTimelinePointerDrag);
    timelineViewport.addEventListener("pointercancel", endTimelinePointerDrag);
    timelineViewport.addEventListener("click", (event) => {
      if (suppressTimelineClick) {
        suppressTimelineClick = false;
        return;
      }
      if (event.target.closest("[data-timeline-clip]")) return;
      const seconds = timelineSecondsFromEvent(event);
      const item = sceneFromTimelinePoint(seconds);
      if (item) {
        selectTimelineScene(item, seconds);
      } else {
        setTimelinePlayhead(seconds);
      }
    });
  }
  window.addEventListener("resize", renderTimeline);

  document.getElementById("expandAll").addEventListener("click", () => {
    cards.forEach((card) => {
      const details = card.querySelector(".details");
      const button = card.querySelector('[data-action="toggle-details"]');
      details.hidden = false;
      button.textContent = "收起";
      button.setAttribute("aria-expanded", "true");
    });
  });

  document.getElementById("collapseAll").addEventListener("click", () => {
    cards.forEach((card) => {
      const details = card.querySelector(".details");
      const button = card.querySelector('[data-action="toggle-details"]');
      details.hidden = true;
      button.textContent = "展开";
      button.setAttribute("aria-expanded", "false");
    });
  });

  document.getElementById("clearReviewed").addEventListener("click", () => {
    try {
      localStorage.removeItem(storageKey);
    } catch (error) {
      showToast("状态未保存");
    }
    applyReviewedState();
    applyFilters();
    showToast("已清空");
  });

  document.getElementById("resetOrder").addEventListener("click", resetOrder);

  document.getElementById("exportEdits").addEventListener("click", () => {
    copyText(JSON.stringify(exportEditedScenes(), null, 2)).then(() => showToast("已复制修改"));
  });

  document.getElementById("resetEdits").addEventListener("click", () => {
    try {
      localStorage.removeItem(editsStorageKey);
    } catch (error) {
      showToast("修改未重置");
    }
    applyEditState();
    renderTimeline();
    showToast("已重置修改");
  });

  document.getElementById("confirmPreset").addEventListener("click", appendPendingPreset);
  document.getElementById("cancelPreset").addEventListener("click", () => {
    pendingPreset = null;
    soundPreviewPanel.hidden = true;
  });
  document.getElementById("replayPreset").addEventListener("click", () => {
    if (pendingPreset) playPresetPreview(pendingPreset.preset);
  });

  sceneGrid.addEventListener("dragover", (event) => {
    if (!draggedCard) return;
    const target = event.target.closest("[data-scene-card]");
    if (!target || target === draggedCard || target.classList.contains("is-hidden")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    clearDropTargets();
    target.classList.add("is-drop-target");
    if (shouldPlaceAfter(target, event.clientX, event.clientY)) {
      target.after(draggedCard);
    } else {
      target.before(draggedCard);
    }
    syncCardsFromDom();
  });

  sceneGrid.addEventListener("drop", (event) => {
    if (!draggedCard) return;
    event.preventDefault();
    finishDragSort();
  });

  cards.forEach((card) => {
    card.addEventListener("focus", () => setActiveCard(card));
    card.addEventListener("click", (event) => {
      if (!event.target.closest("button, input, select, textarea, label")) {
        setActiveCard(card);
      }
      const button = event.target.closest("button");
      if (!button) return;
      if (button.dataset.action === "toggle-details") {
        const details = card.querySelector(".details");
        details.hidden = !details.hidden;
        button.textContent = details.hidden ? "展开" : "收起";
        button.setAttribute("aria-expanded", String(!details.hidden));
      }
      if (button.dataset.action === "preview-preset") {
        previewPreset(card, button.dataset.preset || "");
      }
      if (button.dataset.action === "copy-voiceover") {
        copyText(fieldValue(card, "voiceover")).then(() => showToast("已复制口播"));
      }
      if (button.dataset.action === "copy-assets") {
        copyText(sceneText(card)).then(() => showToast("已复制本格"));
      }
    });
    const dragHandle = card.querySelector("[data-drag-handle]");
    dragHandle.addEventListener("dragstart", (event) => {
      draggedCard = card;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.index);
      card.classList.add("is-dragging");
      setActiveCard(card);
    });
    dragHandle.addEventListener("dragend", finishDragSort);
    const checkbox = card.querySelector(".review-toggle");
    checkbox.addEventListener("change", () => {
      const reviewed = loadReviewed();
      if (checkbox.checked) {
        reviewed.add(card.dataset.index);
      } else {
        reviewed.delete(card.dataset.index);
      }
      saveReviewed(reviewed);
      applyReviewedState();
      applyFilters();
    });
    card.querySelectorAll("[data-edit-field]").forEach((field) => {
      field.addEventListener("input", () => {
        saveField(field);
        renderTimeline();
      });
    });
    const clipSelect = card.querySelector("[data-video-source]");
    if (clipSelect) {
      clipSelect.addEventListener("change", () => updateClipPreview(card, "in"));
    }
    card.querySelectorAll("[data-clip-in], [data-clip-out]").forEach((range) => {
      range.addEventListener("input", () => updateClipPreview(card, range.hasAttribute("data-clip-out") ? "out" : "in"));
      range.addEventListener("change", () => updateClipPreview(card, range.hasAttribute("data-clip-out") ? "out" : "in"));
    });
    const clipPreview = card.querySelector("[data-clip-preview]");
    if (clipPreview) {
      clipPreview.addEventListener("loadedmetadata", () => {
        setClipRangeMax(card, clipPreview.duration);
        seekClipPreview(card, "in");
      });
      clipPreview.addEventListener("timeupdate", () => {
        const range = syncClipRange(card);
        if (!clipPreview.paused && clipPreview.currentTime >= range.outPoint) {
          clipPreview.pause();
          clipPreview.currentTime = range.inPoint;
        }
      });
    }
    syncClipRange(card);
    updateClipPreview(card, "in");
  });

  document.addEventListener("keydown", (event) => {
    const tagName = document.activeElement ? document.activeElement.tagName : "";
    if (tagName === "INPUT" || tagName === "TEXTAREA") return;
    if (event.key === "j" || event.key === "J") {
      event.preventDefault();
      scrollScene(1);
    }
    if (event.key === "k" || event.key === "K") {
      event.preventDefault();
      scrollScene(-1);
    }
  });

  window.scrollScene = scrollScene;
  window.exportEditedScenes = exportEditedScenes;
  window.resetStoryboardOrder = resetOrder;
  window.renderTimeline = renderTimeline;
  window.setTimelinePlayhead = setTimelinePlayhead;
  window.updateTimelineActive = updateTimelineActive;
  applySavedOrder();
  applyReviewedState();
  applyEditState();
  applyFilters();
  renderTimeline();
  if (cards[0]) setActiveCard(cards[0]);
})();
</script>
"""


def _render_field(label: str, value: str) -> str:
    data_attr = " data-matched-asset" if label == "匹配素材" else ""
    return f"""
<div class="row">
  <div class="label">{escape(label)}</div>
  <div class="text"{data_attr}>{escape(value or "空")}</div>
</div>
"""


def _render_video_clip_tool(
    scene: Scene,
    source_file: str,
    out_dir: Optional[Path],
    asset_dirs: Optional[Sequence[Path]] = None,
) -> str:
    candidates = _find_video_candidates(source_file, asset_dirs)
    default_out = min(3.0, scene.duration or 3.0)
    options = [
        '<option value="" data-browser-asset="1">先选择资料库，或使用已扫描到底片视频</option>'
    ]
    for candidate in candidates:
        source_path = str(candidate.resolve())
        options.append(
            f'<option value="{_html_attr(_asset_url(candidate, out_dir))}" '
            f'data-video-path="{_html_attr(source_path)}" '
            f'>{escape(candidate.name)}</option>'
        )

    return f"""
<div class="row clip-tool" data-video-clip-panel>
  <label class="label" for="scene-{scene.index}-clip-source">底片视频</label>
  <select id="scene-{scene.index}-clip-source" class="clip-source" data-video-source>
    {''.join(options)}
  </select>
  <div class="clip-editor">
    <div class="clip-preview-box">
      <video class="clip-preview" data-clip-preview muted controls playsinline preload="metadata"></video>
      <div class="clip-preview-empty" data-clip-preview-empty>选择底片后预览</div>
    </div>
    <div class="clip-trim">
      <div class="clip-trim-head">
        <label for="scene-{scene.index}-clip-in">入点 <output data-clip-in-output>0.0s</output></label>
        <label for="scene-{scene.index}-clip-out">出点 <output data-clip-out-output>{default_out:.1f}s</output></label>
      </div>
      <div class="clip-slider" data-clip-slider>
        <input id="scene-{scene.index}-clip-in" type="range" min="0" max="{default_out:.1f}" step="0.1" value="0" data-clip-in aria-label="入点">
        <input id="scene-{scene.index}-clip-out" type="range" min="0" max="{default_out:.1f}" step="0.1" value="{default_out:.1f}" data-clip-out aria-label="出点">
      </div>
    </div>
  </div>
</div>
"""


def _render_editable_field(scene: Scene, label: str, field: str, value: str) -> str:
    presets = _render_sound_presets() if field == "sound" else ""
    return f"""
<div class="row editable-row">
  <label class="label" for="scene-{scene.index}-{field}">{escape(label)}</label>
  <textarea id="scene-{scene.index}-{field}" class="edit-field" data-edit-field="{field}" data-index="{scene.index}" data-original="{_html_attr(value)}" rows="3">{escape(value or "")}</textarea>
  {presets}
</div>
"""


def _render_sound_presets() -> str:
    buttons = "".join(
        f'<button type="button" data-action="preview-preset" data-preset="{_html_attr(preset)}">{escape(preset)}</button>'
        for preset in SOUND_PRESETS
    )
    return f'<div class="preset-bar" aria-label="常用音效 BGM">{buttons}</div>'


def _find_scene_asset(
    scene: Scene,
    source_file: str,
    asset_dirs: Optional[Sequence[Path]] = None,
) -> Optional[SceneAsset]:
    source_path = Path(source_file)
    source_dir = source_path.parent if source_path.parent != Path("") else Path(".")

    for search_dir, recursive in _asset_search_roots(source_dir, asset_dirs):
        if not search_dir.exists() or not search_dir.is_dir():
            continue
        for candidate in _numbered_asset_candidates(search_dir, scene.index, recursive=recursive):
            kind = _asset_kind(candidate)
            if kind:
                return SceneAsset(path=candidate, kind=kind)
    return None


def _find_video_candidates(source_file: str, asset_dirs: Optional[Sequence[Path]] = None) -> List[Path]:
    source_path = Path(source_file)
    source_dir = source_path.parent if source_path.parent != Path("") else Path(".")
    search_roots = [(source_dir, False)] + [
        (source_dir / name, False) for name in ("storyboard", "assets", "media")
    ]
    search_roots.extend((asset_dir, True) for asset_dir in _normalize_asset_dirs(asset_dirs))
    seen = set()
    candidates: List[Path] = []
    for search_dir, recursive in search_roots:
        if not search_dir.exists() or not search_dir.is_dir():
            continue
        children = search_dir.rglob("*") if recursive else search_dir.iterdir()
        for child in sorted(children, key=lambda item: str(item).lower()):
            if not child.is_file() or _asset_kind(child) != "video":
                continue
            resolved = child.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(child)
    return candidates


def _asset_search_roots(
    source_dir: Path,
    asset_dirs: Optional[Sequence[Path]] = None,
) -> List[Tuple[Path, bool]]:
    roots: List[Tuple[Path, bool]] = [(source_dir / "storyboard", False)]
    roots.extend((asset_dir, True) for asset_dir in _normalize_asset_dirs(asset_dirs))
    roots.extend((source_dir / name, False) for name in ASSET_SEARCH_DIRS if name != "storyboard")

    seen = set()
    unique_roots: List[Tuple[Path, bool]] = []
    for path, recursive in roots:
        key = path.resolve() if path.exists() else path
        if key in seen:
            continue
        seen.add(key)
        unique_roots.append((path, recursive))
    return unique_roots


def _normalize_asset_dirs(asset_dirs: Optional[Sequence[Path]] = None) -> List[Path]:
    if not asset_dirs:
        return []
    normalized: List[Path] = []
    seen = set()
    for asset_dir in asset_dirs:
        path = Path(asset_dir).expanduser()
        key = path.resolve() if path.exists() else path
        if key in seen:
            continue
        seen.add(key)
        normalized.append(path)
    return normalized


def _numbered_asset_candidates(search_dir: Path, index: int, recursive: bool = False) -> List[Path]:
    prefixes = [
        f"{index:02d}_",
        f"{index:02d}-",
        f"{index:02d}.",
        f"{index}_",
        f"{index}-",
        f"{index}.",
        f"scene_{index:02d}",
        f"scene-{index:02d}",
        f"scene_{index}",
        f"scene-{index}",
        f"第{index}格",
    ]
    candidates: List[Path] = []
    children = search_dir.rglob("*") if recursive else search_dir.iterdir()
    for child in sorted(children, key=lambda item: str(item).lower()):
        if not child.is_file() or not _asset_kind(child):
            continue
        stem = child.stem.lower()
        name = child.name.lower()
        if any(stem.startswith(prefix.lower()) or name.startswith(prefix.lower()) for prefix in prefixes):
            candidates.append(child)

    return sorted(candidates, key=_asset_sort_key)


def _asset_sort_key(path: Path) -> Tuple[int, str]:
    kind = _asset_kind(path)
    kind_rank = 0 if kind == "video" else 1
    clip_rank = 0 if "clip" in path.stem.lower() else 1
    return kind_rank, f"{clip_rank}:{path.name.lower()}"


def _asset_kind(path: Path) -> Optional[str]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


def _asset_url(path: Path, out_dir: Optional[Path]) -> str:
    if out_dir:
        relative = os.path.relpath(path.resolve(), start=out_dir.resolve())
        return quote(relative.replace(os.sep, "/"), safe="/._-")
    return path.resolve().as_uri()


def _html_attr(value: str) -> str:
    return escape(value, quote=True).replace("\n", "&#10;")


def _source_generated_at(source_file: str) -> str:
    path = Path(source_file)
    if not path.exists():
        return "unknown"
    return datetime.utcfromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") + "Z"


if __name__ == "__main__":
    raise SystemExit(main())
