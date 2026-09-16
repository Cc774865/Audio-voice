# -*- coding: utf-8 -*-
"""Local FunASR for Chinese and English only (CPU). Requires project .venv (Python 3.11)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
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

# Chinese + English only. Do not load SenseVoice / Fun-ASR-Nano / Qwen3-ASR.
MODELS = {
    "zh": "paraformer-zh",
    "en": "paraformer-en",
}


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
        raw = model.generate(input=str(wav), batch_size_s=60)
    item = raw[0] if isinstance(raw, list) else raw
    text = (item.get("text") if isinstance(item, dict) else str(item)) or ""
    return {
        "id": audio.stem,
        "audio": str(audio),
        "text": text.strip(),
        "engine": f"funasr-{MODELS.get(getattr(model, '_qa_lang', 'zh'), 'paraformer-zh')}",
        "lang": getattr(model, "_qa_lang", "zh"),
        "device": "cpu",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Local FunASR transcription (zh/en only)")
    parser.add_argument("path", nargs="?", help="mp3/wav file or directory")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    parser.add_argument("--warmup", action="store_true", help="download zh+en models and exit")
    args = parser.parse_args()
    if args.warmup:
        for lang in ("zh", "en"):
            print(json.dumps({"warmup": lang, "model": MODELS[lang]}, ensure_ascii=False), flush=True)
            model = load_model(lang)
            model._qa_lang = lang
            print(json.dumps({"warmup": lang, "ok": True}, ensure_ascii=False), flush=True)
        return 0
    if not args.path:
        print("path required unless --warmup", file=sys.stderr)
        return 1
    target = Path(args.path)
    files = [target] if target.is_file() else sorted(target.glob("*.mp3"))
    if not files:
        print("no audio files", file=sys.stderr)
        return 1
    model = load_model(args.lang)
    model._qa_lang = args.lang
    for audio in files:
        result = transcribe(model, audio)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
