# -*- coding: utf-8 -*-
"""Run phase-1 speech QA on one timestamp JSON or a directory."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from analyze_timing import analyze
from score import score_metrics


def report_for(path: Path) -> dict:
    metrics = analyze(path)
    scored = score_metrics(metrics)
    return {
        "id": metrics["id"],
        "gate": scored["gate"],
        "score": scored["score"],
        "raw": scored["raw"],
        "subscores": scored["subscores"],
        "cpm": metrics["cpm"],
        "duration": metrics["duration"],
        "asr": metrics["asr"],
        "transcript_ref": metrics["transcript_ref"],
        "gate_fail_reasons": metrics["gate_fail_reasons"],
        "issues": metrics["issues"],
        "logic": {
            "status": "pending_llm",
            "note": "一期不计入分数。Agent 根据 transcript_ref 判断口播是否合逻辑。",
        },
        "limitations": [
            "asr=skipped：无转写对照，错字错读无法检出",
            "发音/声调未测（无驰声）",
            "自然度未测（无 Auto-ATT）",
        ],
        "calibration": scored["calibration"],
    }


def iter_json(target: Path) -> list[Path]:
    if target.suffix.lower() == ".mp3":
        sibling = target.with_suffix(".json")
        if not sibling.exists():
            raise FileNotFoundError(f"missing timestamp json: {sibling}")
        return [sibling]
    if target.is_file():
        return [target]
    files = sorted(p for p in target.glob("*.json") if p.is_file() and not p.name.endswith(".qa.json"))
    return files


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Phase-1 Chinese speech QA (timing + rule score)")
    parser.add_argument("path", nargs="?", default=".", help="timestamp JSON or directory")
    parser.add_argument("--batch", action="store_true", help="score every *.json in a directory")
    parser.add_argument("--write", action="store_true", help="write <id>.qa.json next to each input")
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        print(f"not found: {target}", file=sys.stderr)
        return 1

    batch = args.batch or target.is_dir()
    files = iter_json(target)
    if not files:
        print("no json files", file=sys.stderr)
        return 1

    reports = [report_for(p) for p in files]
    if args.write:
        for src, rep in zip(files, reports):
            out = src.with_suffix(".qa.json")
            out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    if batch and len(reports) > 1:
        scores = [r["score"] for r in reports]
        summary = {
            "n": len(scores),
            "min": min(scores),
            "max": max(scores),
            "mean": round(statistics.mean(scores), 1),
            "median": round(statistics.median(scores), 1),
            "target_median": [76, 84],
        }
        payload = {"summary": summary, "items": [{"id": r["id"], "score": r["score"], "gate": r["gate"], "cpm": r["cpm"]} for r in reports]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(json.dumps(reports[0], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
