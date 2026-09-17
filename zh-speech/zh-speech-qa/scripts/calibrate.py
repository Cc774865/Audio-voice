# -*- coding: utf-8 -*-
"""Suggest scoring-knob tweaks from pass/fail labels. Never writes score.py."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from statistics import median
from typing import Any

from analyze_timing import MID_GAP_MS, PROLONG_MS, SHORT_COMMA_MS
from cer import CER_ERROR
from memory import disagreement as is_disagreement
from memory import load_all
from qa_course import LOW_SCORE
from score import BASE, COMPRESS

MIN_LABELS = 20
MIN_DISAGREE = 8
MIN_VOTES = 2

STEPS = {
    "LOW_SCORE": 2,
    "CER_ERROR": 0.01,
    "MID_GAP_MS": 50.0,
    "SHORT_COMMA_MS": 20.0,
    "PROLONG_MS": 50.0,
    "BASE": 2.0,
    "COMPRESS": 0.05,
}
CLAMPS = {
    "LOW_SCORE": (70, 84),
    "CER_ERROR": (0.05, 0.12),
    "MID_GAP_MS": (250.0, 500.0),
    "SHORT_COMMA_MS": (80.0, 200.0),
    "PROLONG_MS": (400.0, 700.0),
    "BASE": (50.0, 70.0),
    "COMPRESS": (0.50, 0.90),
}
FILES = {
    "LOW_SCORE": "qa_course.py / SKILL.md / disfluency.md",
    "CER_ERROR": "cer.py / disfluency.md",
    "MID_GAP_MS": "analyze_timing.py / disfluency.md",
    "SHORT_COMMA_MS": "analyze_timing.py / disfluency.md",
    "PROLONG_MS": "analyze_timing.py / disfluency.md",
    "BASE": "score.py / scoring.md",
    "COMPRESS": "score.py / scoring.md",
}

PAUSE_HINT = ("停顿", "逗号", "空隙", "句号")
PROLONG_HINT = ("拖音",)
CER_HINT = ("发音", "CER", "cer", "缺", "听成")


def current_knobs() -> dict[str, float]:
    return {
        "LOW_SCORE": int(LOW_SCORE),
        "CER_ERROR": float(CER_ERROR),
        "MID_GAP_MS": float(MID_GAP_MS),
        "SHORT_COMMA_MS": float(SHORT_COMMA_MS),
        "PROLONG_MS": float(PROLONG_MS),
        "BASE": float(BASE),
        "COMPRESS": float(COMPRESS),
    }


def _bucket(rec: dict[str, Any]) -> str:
    return str(rec.get("bucket") or "").strip().upper() or "OK"


def _score(rec: dict[str, Any]) -> int | None:
    if rec.get("score") is None:
        return None
    try:
        return int(rec["score"])
    except (TypeError, ValueError):
        return None


def _cer_pct(rec: dict[str, Any]) -> float | None:
    if rec.get("cer_pct") is None:
        return None
    try:
        return float(rec["cer_pct"])
    except (TypeError, ValueError):
        return None


def _reason_text(rec: dict[str, Any]) -> str:
    return " ".join(
        str(rec.get(key) or "")
        for key in ("human_reason", "agent_reason", "script_reason")
    )


def _has_hint(text: str, hints: tuple[str, ...]) -> bool:
    return any(h in text for h in hints)


def iter_human(stores: dict[str, list[dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for rec in stores.get("pass") or []:
        rows.append(("pass", rec))
    for rec in stores.get("fail") or []:
        source = str(rec.get("source") or "").strip().lower()
        if not source:
            source = "script" if not str(rec.get("human_reason") or "").strip() else "human"
        if source == "human":
            rows.append(("fail", rec))
    return rows


def count_disagreement(stores: dict[str, list[dict[str, Any]]]) -> int:
    n = 0
    for rec in stores.get("pass") or []:
        if rec.get("disagreement") is True or is_disagreement(_bucket(rec), "pass"):
            n += 1
    for rec in stores.get("fail") or []:
        if rec.get("disagreement") is True or is_disagreement(_bucket(rec), "fail"):
            n += 1
    return n


def _clip_knob(name: str, value: float) -> float:
    lo, hi = CLAMPS[name]
    return max(lo, min(hi, value))


def _nudge(name: str, current: float, direction: str) -> float:
    step = STEPS[name]
    nxt = current + step if direction == "up" else current - step
    nxt = _clip_knob(name, nxt)
    if name in {"LOW_SCORE", "MID_GAP_MS", "SHORT_COMMA_MS", "PROLONG_MS", "BASE"}:
        return int(round(nxt)) if name == "LOW_SCORE" else round(nxt, 1)
    if name == "CER_ERROR":
        return round(nxt, 2)
    return round(nxt, 2)


def classify_votes(human: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    votes: dict[str, dict[str, Any]] = defaultdict(lambda: {"up": 0, "down": 0, "why": []})

    def vote(knob: str, direction: str, why: str) -> None:
        votes[knob][direction] += 1
        votes[knob]["why"].append(why)

    low = int(LOW_SCORE)
    for store, rec in human:
        bid = rec.get("id") or "?"
        bucket = _bucket(rec)
        score = _score(rec)
        cer = _cer_pct(rec)
        text = _reason_text(rec)
        too_strict = store == "pass" and bucket in {"A", "B", "C"}
        too_loose = store == "fail" and bucket in {"", "OK"}

        if too_strict and (bucket == "A" or (cer is not None and cer >= CER_ERROR * 100) or _has_hint(text, CER_HINT)):
            vote("CER_ERROR", "up", f"{bid} 脚本当发音错误、你标合格")
        elif too_loose and _has_hint(text, CER_HINT):
            vote("CER_ERROR", "down", f"{bid} 脚本未判发音错、你标不合格")

        if too_strict and (bucket == "B" or _has_hint(text, PROLONG_HINT)):
            if _has_hint(text, PROLONG_HINT):
                vote("PROLONG_MS", "up", f"{bid} 脚本抓拖音、你标合格")
            else:
                vote("MID_GAP_MS", "up", f"{bid} 脚本判不流畅、你标合格")
                vote("SHORT_COMMA_MS", "up", f"{bid} 脚本判不流畅、你标合格")
        if too_loose and _has_hint(text, PROLONG_HINT):
            vote("PROLONG_MS", "down", f"{bid} 你标不合格（拖音），脚本未卡住")
        if too_loose and _has_hint(text, PAUSE_HINT):
            vote("MID_GAP_MS", "down", f"{bid} 你标不合格（停顿），脚本当合格")
            vote("SHORT_COMMA_MS", "down", f"{bid} 你标不合格（停顿），脚本当合格")

        if too_strict and (bucket == "C" or (score is not None and score < low)):
            vote("LOW_SCORE", "down", f"{bid} 脚本分低/桶 C、你标合格")
        if too_loose and score is not None and score >= low:
            vote("LOW_SCORE", "up", f"{bid} 脚本当合格、你标不合格")

        if store == "pass" and score is not None and score < 70:
            vote("BASE", "up", f"{bid} 合格句分数 {score} 偏低")
            vote("COMPRESS", "up", f"{bid} 合格句分数 {score} 偏低")
        if store == "fail" and score is not None and score >= 80:
            vote("BASE", "down", f"{bid} 不合格句分数 {score} 偏高")
            vote("COMPRESS", "down", f"{bid} 不合格句分数 {score} 偏高")
    return votes


def _pick_suggestions(votes: dict[str, dict[str, Any]], knobs: dict[str, float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, tally in votes.items():
        up, down = int(tally["up"]), int(tally["down"])
        if max(up, down) < MIN_VOTES or up == down:
            continue
        direction = "up" if up > down else "down"
        current = knobs[name]
        nxt = _nudge(name, current, direction)
        if nxt == current:
            continue
        why = "；".join(tally["why"][:3])
        out.append(
            {
                "knob": name,
                "from": current,
                "to": nxt,
                "direction": direction,
                "votes": {"up": up, "down": down},
                "files": FILES[name],
                "reason": why,
            }
        )
    order = ["CER_ERROR", "MID_GAP_MS", "SHORT_COMMA_MS", "PROLONG_MS", "LOW_SCORE", "BASE", "COMPRESS"]
    out.sort(key=lambda row: order.index(row["knob"]) if row["knob"] in order else 99)
    return out[:3]


def _median_fallback(
    human: list[tuple[str, dict[str, Any]]],
    knobs: dict[str, float],
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if existing:
        return existing
    pass_scores = [_score(r) for s, r in human if s == "pass" and _score(r) is not None]
    fail_scores = [_score(r) for s, r in human if s == "fail" and _score(r) is not None]
    if len(pass_scores) >= 5 and median(pass_scores) < 76:
        nxt = _nudge("BASE", knobs["BASE"], "up")
        if nxt != knobs["BASE"]:
            return [
                {
                    "knob": "BASE",
                    "from": knobs["BASE"],
                    "to": nxt,
                    "direction": "up",
                    "votes": {"up": len(pass_scores), "down": 0},
                    "files": FILES["BASE"],
                    "reason": f"合格句中位数 {median(pass_scores):.1f} < 76，分数整体偏低",
                }
            ]
    if len(fail_scores) >= 5 and median(fail_scores) >= 80:
        nxt = _nudge("BASE", knobs["BASE"], "down")
        if nxt != knobs["BASE"]:
            return [
                {
                    "knob": "BASE",
                    "from": knobs["BASE"],
                    "to": nxt,
                    "direction": "down",
                    "votes": {"up": 0, "down": len(fail_scores)},
                    "files": FILES["BASE"],
                    "reason": f"不合格句中位数 {median(fail_scores):.1f} ≥ 80，分数整体偏高",
                }
            ]
    return []


def analyze(stores: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    data = stores if stores is not None else load_all()
    human = iter_human(data)
    n_label = len(human)
    n_disagree = count_disagreement(data)
    n_pass = sum(1 for s, _ in human if s == "pass")
    n_fail = sum(1 for s, _ in human if s == "fail")
    knobs = current_knobs()
    ready = n_label >= MIN_LABELS or n_disagree >= MIN_DISAGREE
    payload: dict[str, Any] = {
        "ready": ready,
        "n_label": n_label,
        "n_pass": n_pass,
        "n_fail_human": n_fail,
        "n_fail_store": len(data.get("fail") or []),
        "n_disagree": n_disagree,
        "need_labels": MIN_LABELS,
        "need_disagree": MIN_DISAGREE,
        "current": knobs,
        "suggestions": [],
        "apply": False,
    }
    if not ready:
        payload["why"] = (
            f"标注 {n_label} 条（需 ≥{MIN_LABELS}）且人机不一致 {n_disagree} 条"
            f"（需 ≥{MIN_DISAGREE}），不出建议。"
        )
        return payload
    votes = classify_votes(human)
    suggestions = _median_fallback(human, knobs, _pick_suggestions(votes, knobs))
    payload["suggestions"] = suggestions
    if suggestions:
        payload["why"] = "样本已达门槛，下面是旋钮建议。未确认不要改文件，也不要重训 FunASR。"
    else:
        payload["why"] = "样本已达门槛，但投票不足以改旋钮。门槛暂稳。"
    return payload


def _fmt_knob(name: str, value: float) -> str:
    if name == "CER_ERROR":
        return f"{value * 100:.0f}%"
    if name in {"MID_GAP_MS", "SHORT_COMMA_MS", "PROLONG_MS"}:
        return f"{value:g}ms"
    if name == "COMPRESS":
        return f"{value:.2f}"
    if name == "BASE":
        return f"{value:g}"
    return str(int(value) if float(value).is_integer() else value)


def render_markdown(report: dict[str, Any]) -> str:
    cur = report["current"]
    lines = [
        f"**校准**：{'可建议' if report['ready'] else '未就绪'}",
        (
            f"**标注**：{report['n_label']} 条（合格 {report['n_pass']} / "
            f"人工不合格 {report['n_fail_human']}，需 ≥{report['need_labels']}）"
        ),
        f"**人机不一致**：{report['n_disagree']} 条（需 ≥{report['need_disagree']}）",
        (
            f"**当前旋钮**：LOW_SCORE {_fmt_knob('LOW_SCORE', cur['LOW_SCORE'])}；"
            f"CER {_fmt_knob('CER_ERROR', cur['CER_ERROR'])}；"
            f"句中停顿 {_fmt_knob('MID_GAP_MS', cur['MID_GAP_MS'])}；"
            f"逗号最短 {_fmt_knob('SHORT_COMMA_MS', cur['SHORT_COMMA_MS'])}；"
            f"拖音 {_fmt_knob('PROLONG_MS', cur['PROLONG_MS'])}；"
            f"BASE {_fmt_knob('BASE', cur['BASE'])}；"
            f"COMPRESS {_fmt_knob('COMPRESS', cur['COMPRESS'])}"
        ),
        report["why"],
        "不重训 FunASR。校准脚本只打印 diff，不改 score.py / scoring.md。",
    ]
    suggestions = report.get("suggestions") or []
    if not report["ready"]:
        return "\n".join(lines)
    lines += ["", "### 建议（需你确认后才改文件）"]
    if not suggestions:
        lines.append("无。门槛暂稳。")
        return "\n".join(lines)
    for i, row in enumerate(suggestions, 1):
        lines.append(
            f"{i}. `{row['knob']}` {_fmt_knob(row['knob'], row['from'])} → "
            f"{_fmt_knob(row['knob'], row['to'])}  （{row['files']}）  \n"
            f"   {row['reason']}"
        )
    scoring = [s for s in suggestions if s["knob"] in {"BASE", "COMPRESS"}]
    if scoring:
        lines += ["", "### scoring.md 建议稿"]
        merged = dict(cur)
        for row in scoring:
            merged[row["knob"]] = row["to"]
        lines.append(f"- `BASE = {merged['BASE']:g}`")
        lines.append(f"- `COMPRESS = {merged['COMPRESS']:.2f}`")
    lines.append("未确认前不要改 score.py / scoring.md，也不要改 CER / 停顿毫秒。")
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Suggest QA knobs from memory labels; never writes files")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = analyze()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
