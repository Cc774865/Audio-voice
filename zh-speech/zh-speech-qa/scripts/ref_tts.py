# -*- coding: utf-8 -*-
"""Synthesize a context-aware reference mp3 for review. Does not write courseware."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

from polyphone import expected_readings

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
PAUSE_RE = re.compile(r"<#[^#>]+#>")


def clean_script(text: str) -> str:
    raw = PAUSE_RE.sub("", text or "")
    raw = raw.replace("……", " ").replace("...", " ")
    return re.sub(r"\s+", " ", raw).strip()


def context_meta(text: str) -> dict:
    script = clean_script(text)
    readings = [
        {
            "char": row["char"],
            "pinyin": row["pinyin"],
            "lexicon_hit": bool(row.get("lexicon_hit")),
        }
        for row in expected_readings(script)
        if row.get("polyphone") or row.get("lexicon_hit")
    ]
    return {"text": script, "expected": readings}


def _cache_key(text: str, voice: str) -> str:
    payload = json.dumps({"text": text, "voice": voice}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


async def _save_edge(text: str, voice: str, dest: Path) -> None:
    import edge_tts

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.mp3")
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(tmp))
    tmp.replace(dest)


def synthesize_plain(text: str, dest: Path, *, voice: str = DEFAULT_VOICE, force: bool = False) -> None:
    """Write mp3 from raw text or SSML. Does not clean pauses or attach sidecar."""
    dest = Path(dest)
    if dest.is_file() and dest.stat().st_size > 200 and not force:
        return
    if not (text or "").strip():
        raise ValueError("empty tts text")
    asyncio.run(_save_edge(text, voice, dest))


def synthesize(text: str, dest: Path, *, voice: str = DEFAULT_VOICE, force: bool = False) -> dict:
    """Generate reference TTS from the full sentence so the model can use context.

    Gold audio must not include courseware 发音修正. Cache by text+voice.
    """
    script = clean_script(text)
    meta = context_meta(script)
    meta["voice"] = voice
    meta["engine"] = "edge-tts"
    if not script:
        raise ValueError("empty script")
    sidecar = dest.with_suffix(".json")
    key = _cache_key(script, voice)
    if dest.is_file() and sidecar.is_file() and not force:
        old = json.loads(sidecar.read_text(encoding="utf-8"))
        if old.get("cache_key") == key and dest.stat().st_size > 200:
            return old
    synthesize_plain(script, dest, voice=voice, force=True)
    meta["cache_key"] = key
    sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
