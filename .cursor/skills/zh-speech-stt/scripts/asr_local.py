# -*- coding: utf-8 -*-
"""Local FunASR for STT only (zh/en, CPU). Independent of the QA scoring skill."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

FFMPEG = Path.home() / "AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.1-full_build/bin/ffmpeg.exe"


def project_root() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / ".venv").is_dir() or (p / ".gitignore").is_file():
            return p
    return here.parents[4]


ROOT = project_root()
CACHE_DIR = ROOT / ".funasr-cache"
MODELS = {"zh": "paraformer-zh", "en": "paraformer-en"}


def _ffmpeg() -> str:
    if FFMPEG.exists():
        return str(FFMPEG)
    from shutil import which

    found = which("ffmpeg")
    if not found:
        raise FileNotFoundError("ffmpeg not found")
    return found


def to_wav16k(src: Path, dst: Path) -> None:
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(dst),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load_model(lang: str = "zh"):
    from funasr import AutoModel

    if lang not in MODELS:
        raise ValueError("lang must be zh or en")
    os.environ.setdefault("MODELSCOPE_CACHE", str(CACHE_DIR))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "model": MODELS[lang],
        "device": "cpu",
        "disable_update": True,
        "hub": "ms",
    }
    if lang == "zh":
        kwargs["vad_model"] = "fsmn-vad"
        kwargs["punc_model"] = "ct-punc"
    return AutoModel(**kwargs)


def transcribe(model, audio: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        to_wav16k(audio, wav)
        with wave.open(str(wav), "rb") as wf:
            wav_ms = int(round(wf.getnframes() / float(wf.getframerate()) * 1000))
        raw = model.generate(input=str(wav), batch_size_s=60)
    item = raw[0] if isinstance(raw, list) else raw
    text = (item.get("text") if isinstance(item, dict) else str(item)) or ""
    timestamp: list[list[int]] = []
    if isinstance(item, dict):
        for pair in item.get("timestamp") or []:
            if pair is None or len(pair) < 2:
                continue
            timestamp.append([int(pair[0]), int(pair[1])])
    last_ts = timestamp[-1][1] if timestamp else 0
    return {
        "id": audio.stem,
        "audio": str(audio),
        "text": text.strip(),
        "timestamp": timestamp,
        "duration_ms": max(last_ts, wav_ms),
        "engine": f"funasr-{MODELS.get(getattr(model, '_stt_lang', 'zh'), 'paraformer-zh')}",
        "lang": getattr(model, "_stt_lang", "zh"),
        "device": "cpu",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="STT FunASR (zh/en)")
    parser.add_argument("path", nargs="?", help="mp3/wav file or directory")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    args = parser.parse_args()
    if not args.path:
        print("path required", file=sys.stderr)
        return 1
    target = Path(args.path)
    files = [target] if target.is_file() else sorted(target.glob("*.mp3"))
    if not files:
        print("no audio files", file=sys.stderr)
        return 1
    model = load_model(args.lang)
    model._stt_lang = args.lang
    for audio in files:
        print(json.dumps(transcribe(model, audio), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
