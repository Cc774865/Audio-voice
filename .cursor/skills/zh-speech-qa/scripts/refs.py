# -*- coding: utf-8 -*-
"""Resolve a clip's correct script: json (timestamps) > txt > md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SKIP_JSON_SUFFIXES = (".qa.json", ".asr.json", ".stt.json")


@dataclass(frozen=True)
class ScriptRef:
    kind: str  # json | txt | md
    path: Path
    transcript: str = ""


def _is_script_json(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".json") and not any(name.endswith(suf) for suf in SKIP_JSON_SUFFIXES)


def load_text_script(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").strip()
    if path.suffix.lower() == ".md":
        raw = re.sub(r"(?m)^#+\s*", "", raw)
        raw = re.sub(r"\*\*(.+?)\*\*", r"\1", raw)
        raw = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", raw)
        raw = re.sub(r"`([^`]+)`", r"\1", raw)
        raw = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw)
    return raw.strip()


def resolve_ref(folder: Path, stem: str) -> ScriptRef | None:
    json_path = folder / f"{stem}.json"
    if json_path.is_file() and _is_script_json(json_path):
        return ScriptRef(kind="json", path=json_path)
    txt_path = folder / f"{stem}.txt"
    if txt_path.is_file():
        return ScriptRef(kind="txt", path=txt_path, transcript=load_text_script(txt_path))
    md_path = folder / f"{stem}.md"
    if md_path.is_file():
        return ScriptRef(kind="md", path=md_path, transcript=load_text_script(md_path))
    return None


def pair_clips(folder: Path) -> tuple[list[tuple[Path, ScriptRef]], list[str]]:
    skipped: list[str] = []
    pairs: list[tuple[Path, ScriptRef]] = []
    mp3s = {p.stem: p for p in folder.glob("*.mp3")}
    for stem, mp3 in sorted(mp3s.items()):
        ref = resolve_ref(folder, stem)
        if ref:
            pairs.append((mp3, ref))
        else:
            skipped.append(f"{mp3.name} (missing json/txt/md)")
    for path in sorted(folder.iterdir(), key=lambda p: p.name):
        if not path.is_file() or path.stem in mp3s:
            continue
        if _is_script_json(path) or path.suffix.lower() in {".txt", ".md"}:
            skipped.append(f"{path.name} (missing mp3)")
    return pairs, skipped
