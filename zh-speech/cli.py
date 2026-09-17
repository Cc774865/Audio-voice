# -*- coding: utf-8 -*-
"""Standalone CLI for speech QA / STT. Does not depend on Cursor."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent
QA_SCRIPTS = PACK / "zh-speech-qa" / "scripts"
STT_SCRIPTS = PACK / "zh-speech-stt" / "scripts"

COMMANDS = {
    "qa": (QA_SCRIPTS, "qa_course"),
    "stt": (STT_SCRIPTS, "stt_course"),
    "calibrate": (QA_SCRIPTS, "calibrate"),
    "memory": (QA_SCRIPTS, "memory"),
    "compile-polyphones": (QA_SCRIPTS, "compile_polyphones"),
    "warmup": (QA_SCRIPTS, "asr_local"),
}


def _run(scripts: Path, module: str, argv: list[str]) -> int:
    sys.path.insert(0, str(scripts))
    sys.argv = [str(scripts / f"{module}.py"), *argv]
    imported = importlib.import_module(module)
    return int(imported.main())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="zh-speech",
        description="Portable Chinese courseware speech QA and transcription",
    )
    parser.add_argument(
        "command",
        choices=tuple(COMMANDS),
        help="qa=score against script; stt=transcribe only; never mix in one run",
    )
    args, extra = parser.parse_known_args()
    if extra and extra[0] == "--":
        extra = extra[1:]
    if args.command == "warmup":
        extra = ["--warmup", *extra]
    scripts, module = COMMANDS[args.command]
    return _run(scripts, module, extra)


if __name__ == "__main__":
    raise SystemExit(main())
