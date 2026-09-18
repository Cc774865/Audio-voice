# -*- coding: utf-8 -*-
"""Measure per-character base/tone recognition against known TTS readings.

Each case synthesizes a real lexicon phrase (or a homophone carrier) whose reading is
known, crops the polyphone, and asks guess_pinyin which reading it hears. The accuracy
per confidence bucket is what the review stage trusts; without enough accuracy the
review must fall back to 待审 (unresolved) instead of claiming a mismatch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from homophones import default_pinyin, replacement
from pinyin_audio import _crop_phrase_char, confidence, guess_pinyin, template_phrase
from polyphone import _load_wav, format_pinyin, load_lexicon, parse_pinyin
from ref_tts import DEFAULT_VOICE, synthesize_plain

QA_ROOT = Path(__file__).resolve().parent.parent
CONF_PATH = QA_ROOT / "rules" / "pinyin_confidence.json"


def build_cases(limit: int = 0) -> list[dict]:
    lex = load_lexicon()
    cases: list[dict] = []
    for ch, entries in sorted(lex.items()):
        readings = [str(e.get("pinyin") or "") for e in entries if e.get("pinyin")]
        bases = {parse_pinyin(r)[0] for r in readings}
        if len(bases) < 2:
            continue
        for ent in entries:
            pinyin = str(ent.get("pinyin") or "")
            if not pinyin:
                continue
            phrase = template_phrase(ch, pinyin)
            if phrase == ch or ch not in phrase:
                repl = replacement(ch, pinyin, {ch} | set(phrase))
                if not repl:
                    continue
                phrase = repl
            cases.append({"char": ch, "pinyin": pinyin, "phrase": phrase, "candidates": readings})
    if limit:
        cases = cases[:limit]
    return cases


def _row(case: dict) -> dict:
    base, tone = parse_pinyin(case["pinyin"])
    return {
        "char": case["char"],
        "index": 0,
        "pinyin": format_pinyin(base, tone),
        "base": base,
        "tone": tone,
        "polyphone": True,
        "check_audio": True,
        "lexicon_hit": True,
        "candidates": case["candidates"],
    }


def evaluate(case: dict, tpl_dir: Path, voice: str) -> dict | None:
    phrase = case["phrase"]
    mp3 = tpl_dir / f"selftest_{phrase}.mp3"
    try:
        synthesize_plain(phrase, mp3, voice=voice)
    except Exception:
        return None
    audio, sr = _load_wav(mp3)
    crop = _crop_phrase_char(audio, sr, phrase, case["char"])
    if phrase == case["char"]:
        crop = audio
    row = _row(case)
    res = guess_pinyin(crop, sr, case["char"], tpl_dir, voice=voice, expected=row)
    want_base, want_tone = parse_pinyin(case["pinyin"])
    if not res:
        return {"ok_base": False, "ok_tone": False, "res": None, "want": case["pinyin"], "got": None}
    return {
        "ok_base": res["base"] == want_base,
        "ok_tone": res["tone"] == want_tone,
        "want": case["pinyin"],
        "got": res.get("pinyin"),
        "base_confident": bool(res.get("base_confident")),
        "tone_confident": bool(res.get("tone_confident")),
        "res": res,
    }


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    ok_base = sum(1 for r in rows if r["ok_base"])
    ok_tone = sum(1 for r in rows if r["ok_tone"])
    both = sum(1 for r in rows if r["ok_base"] and r["ok_tone"])
    tone_conf = [r for r in rows if r["tone_confident"]]
    base_conf = [r for r in rows if r["base_confident"]]
    return {
        "n": n,
        "base_acc": round(ok_base / n, 3),
        "tone_acc": round(ok_tone / n, 3),
        "both_acc": round(both / n, 3),
        "tone_conf_n": len(tone_conf),
        "tone_conf_acc": round(sum(1 for r in tone_conf if r["ok_tone"]) / len(tone_conf), 3) if tone_conf else None,
        "base_conf_n": len(base_conf),
        "base_conf_acc": round(sum(1 for r in base_conf if r["ok_base"]) / len(base_conf), 3) if base_conf else None,
        "misses": [
            {"want": r["want"], "got": r["got"]}
            for r in rows
            if not (r["ok_base"] and r["ok_tone"])
        ][:20],
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Calibrate per-character pinyin recognition")
    parser.add_argument("--limit", type=int, default=80, help="max cases (0 = all)")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true", help="write rules/pinyin_confidence.json")
    args = parser.parse_args()

    tpl_dir = QA_ROOT.parent / ".funasr-cache" / "pinyin-selftest"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    cases = build_cases(args.limit)
    rows: list[dict] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['char']} {case['pinyin']} {case['phrase']}", file=sys.stderr)
        out = evaluate(case, tpl_dir, args.voice)
        if out:
            rows.append(out)
    report = summarize(rows)
    report["config"] = confidence()
    report["suggest"] = {
        "min_cosine": confidence()["min_cosine"],
        "base_margin": confidence()["base_margin"],
        "tone_conf": confidence()["tone_conf"],
        "tone_f0_min": confidence()["tone_f0_min"],
        "tone_margin": confidence()["tone_margin"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.write:
        CONF_PATH.write_text(json.dumps(report["suggest"], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {CONF_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
