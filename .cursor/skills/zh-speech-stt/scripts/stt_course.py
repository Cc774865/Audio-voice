# -*- coding: utf-8 -*-
"""mp3 → transcript + fluency notes + cleaned text. Independent of QA scoring."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from asr_local import CACHE_DIR, _ffmpeg, load_model, transcribe
from fluency import SPEED_MARGIN, SPEED_OK, inspect


def list_audio(target: Path) -> list[Path]:
    if target.is_file() and target.suffix.lower() in {".mp3", ".wav"}:
        return [target]
    if not target.is_dir():
        return []
    return sorted(target.glob("*.mp3"))


def cached_stt(mp3: Path, model, force: bool) -> dict:
    cache = mp3.with_suffix(".stt.json")
    if cache.exists() and not force:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("text") and data.get("timestamp"):
            return data
    os.environ.setdefault("MODELSCOPE_CACHE", str(CACHE_DIR))
    result = transcribe(model, mp3)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def evaluate(mp3: Path, model, force: bool) -> dict:
    asr = cached_stt(mp3, model, force)
    text = asr.get("text") or ""
    duration = float(asr.get("duration_ms") or 0) / 1000.0
    flu = inspect(text, asr.get("timestamp"), duration)
    cleaned = flu["text_clean"]
    parts = [
        f"停顿{flu['pause_n']}",
        f"拖音{flu['prolong_n']}",
        f"吞音{flu['swallow_n']}",
        f"语气词{flu['filler_n']}",
        f"重复{flu['repeat_n']}",
    ]
    if not flu["speed_in_band"]:
        parts.append("语速偏快或偏慢")
    preview = [x["detail"] for x in flu["issues"][:5]]
    return {
        "id": mp3.stem,
        "text": text,
        "text_clean": cleaned,
        "changed": cleaned != text,
        "cpm": flu["cpm"],
        "speed_in_band": flu["speed_in_band"],
        "fluency": " · ".join(parts),
        "issue_preview": preview,
        "issue_n": len(flu["issues"]),
    }


def render_markdown(folder: str, rows: list[dict]) -> str:
    lo, hi = SPEED_OK
    lines = [
        f"**转写**：{len(rows)} 条",
        f"**目录**：`{folder}`",
        f"**语速参考**：{lo:.0f}–{hi:.0f} 字/分（±{SPEED_MARGIN:.0f}）",
        "",
    ]
    for i, row in enumerate(rows, 1):
        lines.append(f"### {i}. `{row['id']}`")
        lines.append(f"- 原文：{row['text'] or '（空）'}")
        lines.append(f"- 优化：{row['text_clean'] if row['changed'] else '与原文相同'}")
        band = "正常" if row.get("speed_in_band") else "偏快或偏慢"
        lines.append(f"- 语速：{row.get('cpm')} 字/分（{band}）")
        lines.append(f"- 听感：{row['fluency']}")
        preview = row.get("issue_preview") or []
        if preview:
            extra = f" 等 {row['issue_n']} 处" if int(row.get("issue_n") or 0) > len(preview) else ""
            lines.append("- 备注：" + "；".join(preview) + extra)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.environ["PATH"] = str(Path(_ffmpeg()).parent) + os.pathsep + os.environ.get("PATH", "")
    parser = argparse.ArgumentParser(description="Speech-to-text with fluency notes")
    parser.add_argument("path", nargs="?", default=".", help="mp3 file or directory")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--force-asr", action="store_true")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    args = parser.parse_args()
    target = Path(args.path).resolve()
    files = list_audio(target)
    if not files:
        print("no mp3 files", file=sys.stderr)
        return 1
    print(f"loading FunASR {args.lang} ({len(files)} clips)…", file=sys.stderr)
    model = load_model(args.lang)
    model._stt_lang = args.lang
    rows = []
    for i, mp3 in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {mp3.name}", file=sys.stderr)
        rows.append(evaluate(mp3, model, args.force_asr))
    folder = target.name if target.is_dir() else target.parent.name
    if args.json:
        print(json.dumps({"folder": folder, "n": len(rows), "items": rows}, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(folder, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
