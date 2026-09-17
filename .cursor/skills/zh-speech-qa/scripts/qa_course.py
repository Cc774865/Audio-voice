# -*- coding: utf-8 -*-
"""Course-level QA: FunASR bucket A + fluency B + low-score C, one score, 6 examples."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

from analyze_timing import SPEED_MARGIN, SPEED_OK, analyze, analyze_words, words_from_asr
from asr_local import CACHE_DIR, load_model, transcribe
from cer import pronunciation_report
from memory import load_all, neighbors_for
from refs import ScriptRef, pair_clips
from score import score_metrics

TYPICAL_N = 6
B_MAX = 4
LOW_SCORE = 76
ERROR_PENALTY_CAP = 20.0


def clip01(value: float) -> float:
    return max(0.0, min(100.0, value))


def cached_asr(mp3: Path, model, force: bool, *, need_timestamp: bool = False) -> dict:
    cache = mp3.with_suffix(".asr.json")
    if cache.exists() and not force:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("text") and (not need_timestamp or data.get("timestamp")):
            return data
    os.environ.setdefault("MODELSCOPE_CACHE", str(CACHE_DIR))
    result = transcribe(model, mp3)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def disfluency_rank(rep: dict) -> int:
    return (
        int(rep.get("pause_events") or 0) * 3
        + int(rep.get("prolong_n") or 0) * 2
        + int(rep.get("swallow_n") or 0)
        + (0 if rep.get("speed_in_band") else 2)
    )


def is_disfluent(rep: dict) -> bool:
    if disfluency_rank(rep) > 0:
        return True
    subs = rep.get("subscores") or {}
    return int(subs.get("fluency") or 100) < 80 or int(subs.get("pause") or 100) < 80


def bucket_of(rep: dict) -> str:
    if rep.get("bucket_a"):
        return "A"
    if is_disfluent(rep):
        return "B"
    if int(rep.get("score") or 100) < LOW_SCORE:
        return "C"
    return "ok"


def pick_typical(items: list[dict]) -> list[dict]:
    rest = [x for x in items if x["bucket"] != "A"]
    picked: list[dict] = []
    seen: set[str] = set()

    def take(row: dict) -> None:
        if row["id"] in seen or len(picked) >= TYPICAL_N:
            return
        seen.add(row["id"])
        picked.append(row)

    bucket_b = sorted((x for x in rest if x["bucket"] == "B"), key=disfluency_rank, reverse=True)
    for row in bucket_b[:B_MAX]:
        take(row)
    bucket_c = sorted((x for x in rest if x["bucket"] == "C"), key=lambda x: x["score"])
    for row in bucket_c:
        take(row)
    leftover = [x for x in rest if x["id"] not in seen and x["bucket"] == "ok"]
    if leftover and len(picked) < TYPICAL_N:
        leftover_sorted = sorted(leftover, key=lambda x: x["score"])
        n = len(leftover_sorted)
        anchors = [leftover_sorted[0], leftover_sorted[n // 2], leftover_sorted[-1]]
        for row in anchors:
            take(row)
        for row in leftover_sorted:
            take(row)
    if len(picked) < TYPICAL_N:
        for row in rest:
            take(row)
    return picked


def course_score(items: list[dict]) -> dict:
    if not items:
        return {"score": 0, "base": 0, "penalty": 0, "error_rate": 0}
    dur = sum(float(x["duration"]) or 0.001 for x in items)
    base = sum(int(x["score"]) * (float(x["duration"]) or 0.001) for x in items) / dur
    n = len(items)
    n_err = sum(1 for x in items if x["bucket"] == "A")
    penalty = min(ERROR_PENALTY_CAP, 80.0 * n_err / n)
    return {
        "score": int(round(clip01(base - penalty))),
        "base": round(base, 1),
        "penalty": round(penalty, 1),
        "error_rate": round(n_err / n, 4),
        "median": round(statistics.median(x["score"] for x in items), 1),
    }


def compact(row: dict) -> dict:
    return {
        "id": row["id"],
        "course": row.get("course"),
        "score": row["score"],
        "bucket": row["bucket"],
        "cer_pct": row.get("cer_pct"),
        "pause_events": row.get("pause_events"),
        "reason": row.get("reason"),
        "transcript_ref": row.get("transcript_ref"),
        "transcript_asr": row.get("transcript_asr"),
        "cpm": row.get("cpm"),
        "ref_kind": row.get("ref_kind"),
    }


def attach_typical_neighbors(rows: list[dict], stores: dict) -> list[dict]:
    """Hang pass/fail nearest neighbors on typical clips. Does not change scores."""
    out = []
    has_store = bool(stores.get("pass") or stores.get("fail"))
    for row in rows:
        item = compact(row)
        if has_store:
            nb = neighbors_for(row, stores=stores)
            if nb["pass"] or nb["fail"]:
                item["neighbors"] = nb
        out.append(item)
    return out


def _clip_text(text: str | None, n: int = 28) -> str:
    raw = str(text or "").replace("\n", "")
    return raw if len(raw) <= n else raw[:n] + "…"


def _neighbor_md(kind: str, row: dict) -> str:
    extra = f" CER {row['cer_pct']}%" if row.get("cer_pct") is not None else ""
    pause = f" 停顿{int(row['pause_events'])}" if row.get("pause_events") is not None else ""
    why = row.get("human_reason") or row.get("agent_reason") or row.get("script_reason") or ""
    why_part = f"  {why}" if why else ""
    score = row.get("score")
    score_part = f" {score}分" if score is not None else ""
    return (
        f"   - 近邻{kind}：`{row.get('id')}`{score_part}{extra}{pause}{why_part}  "
        f"「{_clip_text(row.get('transcript_ref'))}」"
    )


def evaluate_pair(mp3: Path, ref: ScriptRef, model, force: bool) -> dict:
    need_ts = ref.kind != "json"
    asr = cached_asr(mp3, model, force, need_timestamp=need_ts)
    hyp = asr.get("text") or ""
    if ref.kind == "json":
        metrics = analyze(ref.path)
    else:
        duration = float(asr.get("duration_ms") or 0) / 1000.0
        words = words_from_asr(hyp, asr.get("timestamp"), duration)
        metrics = analyze_words(
            words,
            duration,
            clip_id=mp3.stem,
            path=str(mp3),
            timing_source="asr",
        )
        metrics["transcript_ref"] = ref.transcript
    pron = pronunciation_report(metrics["transcript_ref"], hyp)
    metrics["asr"] = "funasr-zh"
    metrics["cer"] = pron["cer"]
    metrics["missing_keywords"] = pron["missing_keywords"]
    if pron["is_error"]:
        detail = f"CER {pron['cer_pct']}%"
        if pron["missing_keywords"]:
            detail += " 缺：" + "、".join(pron["missing_keywords"])
        metrics["issues"] = list(metrics["issues"]) + [
            {"type": "mispronunciation", "at_ms": None, "detail": detail}
        ]
    scored = score_metrics(metrics)
    row = {
        "id": metrics["id"],
        "score": scored["score"],
        "gate": scored["gate"],
        "subscores": scored["subscores"],
        "cpm": metrics["cpm"],
        "duration": metrics["duration"],
        "speed_in_band": metrics["speed_in_band"],
        "pause_events": metrics["pause_events"],
        "swallow_n": metrics["swallow_n"],
        "prolong_n": metrics["prolong_n"],
        "transcript_ref": metrics["transcript_ref"],
        "transcript_asr": hyp,
        "cer": pron["cer"],
        "cer_pct": pron["cer_pct"],
        "missing_keywords": pron["missing_keywords"],
        "gate_fail_reasons": metrics["gate_fail_reasons"],
        "issues": metrics["issues"],
        "bucket_a": bool(pron["is_error"] or metrics["gate_fail_reasons"]),
        "ref_kind": ref.kind,
        "_metrics": metrics,
    }
    row["bucket"] = bucket_of(row)
    row["reason"] = _reason(row)
    return row


def _reason(row: dict) -> str:
    reasons = []
    if row.get("missing_keywords") or (row.get("cer") is not None and row["cer"] >= 0.08):
        if row.get("cer_pct") is not None:
            reasons.append(f"发音 CER {row['cer_pct']}%")
        if row.get("missing_keywords"):
            reasons.append("缺 " + "、".join(row["missing_keywords"]))
    if row.get("gate_fail_reasons"):
        reasons.extend(row["gate_fail_reasons"])
    if row.get("bucket") == "B":
        reasons.append(f"不流畅 rank={disfluency_rank(row)}")
    if row.get("bucket") == "C":
        reasons.append(f"综合分 {row['score']} < {LOW_SCORE}")
    return "；".join(reasons) if reasons else "合格"


def apply_speed_band(row: dict, speed_ok: tuple[float, float]) -> None:
    metrics = row["_metrics"]
    lo, hi = speed_ok
    metrics["speed_in_band"] = lo <= float(metrics["cpm"]) <= hi
    scored = score_metrics(metrics, speed_ok=speed_ok)
    row["score"] = scored["score"]
    row["subscores"] = scored["subscores"]
    row["speed_in_band"] = metrics["speed_in_band"]
    row["bucket"] = bucket_of(row)
    row["reason"] = _reason(row)


def render_markdown(payload: dict) -> str:
    s = payload["summary"]
    lines = [
        f"**课件综合分**：{s['score']} / 100",
        f"**目录**：`{s.get('folder', '—')}`",
        f"**句数**：{s['n']}（错误 {s['n_error']} / 不流畅 {s['n_disfluent']} / 其余 {s['n_ok']}）",
        f"**FunASR**：{s['asr']}",
        f"**语速合格带**：{s.get('speed_band', '—')}（当课均值±{SPEED_MARGIN}）",
        f"**单句中位数**：{s['median']}",
        f"**正确稿**：json {s.get('n_json', 0)} / txt {s.get('n_txt', 0)} / md {s.get('n_md', 0)}",
    ]
    mem = payload.get("memory") or {}
    if mem.get("pass_n") or mem.get("fail_n"):
        lines.append(
            f"**记忆库**：合格 {mem.get('pass_n', 0)} / 不合格 {mem.get('fail_n', 0)}"
            "（近邻挂在 6 例旁，不改硬分）"
        )
    lines += [
        "",
        "### 错误（优先，不计入 6 例）",
    ]
    errors = payload["errors"]
    if not errors:
        lines.append("无")
    else:
        for i, row in enumerate(errors, 1):
            lines.append(
                f"{i}. `{row['id']}` {row['reason']}  "
                f"原稿「{row['transcript_ref']}」 ASR「{row['transcript_asr']}」"
            )
    lines += ["", "### 6 个典型例"]
    typical = payload["typical"]
    if not typical:
        lines.append("无（非错误句不足）")
    else:
        labels = {"B": "不流畅", "C": "分低", "ok": "合格对照"}
        for i, row in enumerate(typical, 1):
            tag = labels.get(row["bucket"], row["bucket"])
            extra = f" CER {row['cer_pct']}%" if row.get("cer_pct") is not None else ""
            lines.append(
                f"{i}. [{tag}] `{row['id']}` {row['score']}分{extra}  {row['reason']}  "
                f"「{row['transcript_ref']}」"
            )
            nb = row.get("neighbors") or {}
            for hit in nb.get("pass") or []:
                lines.append(_neighbor_md("合格", hit))
            for hit in nb.get("fail") or []:
                lines.append(_neighbor_md("不合格", hit))
        if len(typical) < TYPICAL_N:
            lines.append(f"（typical_count={len(typical)} < 6）")
    if payload.get("skipped"):
        lines += ["", "### 跳过", *[f"- {x}" for x in payload["skipped"]]]
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from asr_local import _ffmpeg

    ffmpeg_bin = Path(_ffmpeg()).parent
    os.environ["PATH"] = str(ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")
    parser = argparse.ArgumentParser(description="Course-level speech QA with FunASR bucket A")
    parser.add_argument("path", nargs="?", default=".", help="directory of mp3 + json/txt/md pairs")
    parser.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    parser.add_argument("--force-asr", action="store_true", help="ignore *.asr.json cache")
    parser.add_argument("--no-memory", action="store_true", help="do not attach pass/fail neighbors")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    args = parser.parse_args()
    folder = Path(args.path).resolve()
    if not folder.is_dir():
        print(f"not a directory: {folder}", file=sys.stderr)
        return 1
    pairs, skipped = pair_clips(folder)
    if not pairs:
        print("no mp3 + json/txt/md pairs", file=sys.stderr)
        return 1

    print(f"loading FunASR {args.lang} ({len(pairs)} clips)…", file=sys.stderr)
    model = load_model(args.lang)
    model._qa_lang = args.lang

    items = []
    for i, (mp3, ref) in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] {mp3.name} ({ref.kind})", file=sys.stderr)
        items.append(evaluate_pair(mp3, ref, model, args.force_asr))
    for row in items:
        row["course"] = folder.name

    mean_cpm = statistics.mean(x["cpm"] for x in items)
    speed_ok = (mean_cpm - SPEED_MARGIN, mean_cpm + SPEED_MARGIN)
    for row in items:
        apply_speed_band(row, speed_ok)

    errors = sorted(
        (x for x in items if x["bucket"] == "A"),
        key=lambda x: (-float(x.get("cer") or 0), x["score"]),
    )
    typical = pick_typical(items)
    stores = {"pass": [], "fail": []} if args.no_memory else load_all()
    typical_out = attach_typical_neighbors(typical, stores)
    agg = course_score(items)
    n_b = sum(1 for x in items if x["bucket"] == "B")
    n_ok = sum(1 for x in items if x["bucket"] == "ok")
    payload = {
        "summary": {
            "folder": folder.name,
            "score": agg["score"],
            "base": agg["base"],
            "penalty": agg["penalty"],
            "n": len(items),
            "n_error": len(errors),
            "n_disfluent": n_b,
            "n_ok": n_ok,
            "median": agg["median"],
            "asr": f"funasr-paraformer-{args.lang}",
            "speed_mean": round(mean_cpm, 1),
            "speed_band": f"{speed_ok[0]:.0f}–{speed_ok[1]:.0f} 字/分",
            "n_json": sum(1 for x in items if x.get("ref_kind") == "json"),
            "n_txt": sum(1 for x in items if x.get("ref_kind") == "txt"),
            "n_md": sum(1 for x in items if x.get("ref_kind") == "md"),
        },
        "errors": [compact(x) for x in errors],
        "typical": typical_out,
        "skipped": skipped,
    }
    if not args.no_memory:
        payload["memory"] = {"pass_n": len(stores["pass"]), "fail_n": len(stores["fail"])}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
