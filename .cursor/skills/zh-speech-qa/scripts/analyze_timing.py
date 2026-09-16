# -*- coding: utf-8 -*-
"""Parse TTS word-timestamp JSON and extract fluency / pause / text issues."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PUNCT = set("，。？！、；：,.!?;:…—～~·\"'“”‘’（）()【】[]《》<> ")
SENT_END = set("。？！.?!")
COMMA = set("，、；,;")
PARTICLES = set("的了着过吗呢吧呀嘛哇哦噢哈地得")
FILLERS = {"嗯", "呃", "额", "唔", "哎", "诶", "欸"}
FILLER_PHRASES = (("那", "个", "那", "个"), ("就", "是", "就", "是"))
MID_GAP_MS = 350.0
LONG_COMMA_MS = 400.0
LONG_END_MS = 800.0
SWALLOW_MS = 70.0
PROLONG_MS = 450.0
SPEED_OK = (180.0, 280.0)


def is_punct(token: str) -> bool:
    return bool(token) and all(ch in PUNCT for ch in token)


def is_speech(token: str) -> bool:
    return bool(token) and not is_punct(token)


def load_clip(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    words = data.get("words") or []
    duration = float(data.get("duration") or 0)
    if duration <= 0 and words:
        duration = max(float(w.get("end") or 0) for w in words) / 1000.0
    return {"path": str(p), "id": p.stem, "duration": duration, "words": words}


def transcript_of(words: list[dict[str, Any]]) -> str:
    return "".join(str(w.get("word") or "") for w in words)


def speech_tokens(words: list[dict[str, Any]]) -> list[str]:
    return [str(w.get("word") or "") for w in words if is_speech(str(w.get("word") or ""))]


def _dur(w: dict[str, Any]) -> float:
    return max(0.0, float(w.get("end") or 0) - float(w.get("begin") or 0))


def analyze(path: str | Path) -> dict[str, Any]:
    clip = load_clip(path)
    words = clip["words"]
    duration = clip["duration"]
    transcript = transcript_of(words)
    speech = speech_tokens(words)
    char_count = len(speech)
    cpm = (char_count * 60.0 / duration) if duration > 0 else 0.0

    issues: list[dict[str, Any]] = []
    pause_events = 0
    swallow_n = 0
    prolong_n = 0
    filler_n = 0
    repeat_n = 0
    fragment_n = 0

    for i, w in enumerate(words):
        token = str(w.get("word") or "")
        begin = float(w.get("begin") or 0)
        end = float(w.get("end") or 0)
        dur = _dur(w)

        if i + 1 < len(words):
            nxt = words[i + 1]
            gap = float(nxt.get("begin") or 0) - end
            nxt_tok = str(nxt.get("word") or "")
            if gap >= MID_GAP_MS and is_speech(token) and is_speech(nxt_tok):
                pause_events += 1
                issues.append(
                    {
                        "type": "pause",
                        "at_ms": round(end, 2),
                        "detail": f"句中空隙 {gap:.0f}ms（{token} → {nxt_tok}）",
                    }
                )

        if token in COMMA and dur >= LONG_COMMA_MS:
            pause_events += 1
            issues.append(
                {
                    "type": "pause",
                    "at_ms": round(begin, 2),
                    "detail": f"逗号过长 {dur:.0f}ms",
                }
            )
        if token in SENT_END and dur >= LONG_END_MS:
            pause_events += 1
            issues.append(
                {
                    "type": "pause",
                    "at_ms": round(begin, 2),
                    "detail": f"句末停顿过长 {dur:.0f}ms",
                }
            )

        if is_speech(token) and token not in PARTICLES and len(token) == 1:
            if dur > 0 and dur < SWALLOW_MS:
                swallow_n += 1
                issues.append(
                    {
                        "type": "swallow",
                        "at_ms": round(begin, 2),
                        "detail": f"疑似吞音「{token}」仅 {dur:.0f}ms",
                    }
                )
            if dur >= PROLONG_MS:
                prolong_n += 1
                issues.append(
                    {
                        "type": "prolong",
                        "at_ms": round(begin, 2),
                        "detail": f"拖音「{token}」{dur:.0f}ms",
                    }
                )

        if token in FILLERS:
            filler_n += 1
            issues.append(
                {
                    "type": "filler",
                    "at_ms": round(begin, 2),
                    "detail": f"语气词「{token}」",
                }
            )

    for i in range(len(speech) - 1):
        if speech[i] == speech[i + 1] and is_speech(speech[i]):
            repeat_n += 1
            issues.append(
                {
                    "type": "repeat",
                    "at_ms": None,
                    "detail": f"连续重复「{speech[i]}{speech[i + 1]}」",
                }
            )

    joined = speech
    for phrase in FILLER_PHRASES:
        n = len(phrase)
        for i in range(len(joined) - n + 1):
            if tuple(joined[i : i + n]) == phrase:
                filler_n += 1
                issues.append(
                    {
                        "type": "filler",
                        "at_ms": None,
                        "detail": f"卡顿词「{''.join(phrase)}」",
                    }
                )

    stripped = transcript.strip()
    if stripped and stripped[-1] not in SENT_END:
        fragment_n += 1
        issues.append({"type": "fragment", "at_ms": None, "detail": "口播未以句末标点收束，疑似残句"})

    # 标点后仍是残片：连续两个句末标点之间过短且无实词
    sentences = [s for s in re.split(r"[。？！?!]", stripped) if s.strip()]
    for s in sentences:
        body = re.sub(r"[，、；,.]", "", s).strip()
        if 0 < len(body) <= 1:
            fragment_n += 1
            issues.append({"type": "fragment", "at_ms": None, "detail": f"残句「{s.strip()}」"})

    has_question = "？" in transcript or "?" in transcript
    weak_question = False
    if has_question:
        q_durs = [_dur(w) for w in words if str(w.get("word") or "") in {"？", "?"}]
        if q_durs and max(q_durs) < 80:
            weak_question = True
            issues.append(
                {
                    "type": "prosody",
                    "at_ms": None,
                    "detail": "问句停顿过短，语调可能未上扬",
                }
            )

    speed_in_band = SPEED_OK[0] <= cpm <= SPEED_OK[1]
    gate_fail_reasons: list[str] = []
    if fragment_n:
        gate_fail_reasons.append("残句")
    if repeat_n >= 2:
        gate_fail_reasons.append("多处重复")

    return {
        "id": clip["id"],
        "path": clip["path"],
        "duration": round(duration, 3),
        "transcript_ref": transcript,
        "asr": "skipped",
        "char_count": char_count,
        "cpm": round(cpm, 1),
        "speed_in_band": speed_in_band,
        "pause_events": pause_events,
        "swallow_n": swallow_n,
        "prolong_n": prolong_n,
        "filler_n": filler_n,
        "repeat_n": repeat_n,
        "fragment_n": fragment_n,
        "has_question": has_question,
        "weak_question": weak_question,
        "gate_fail_reasons": gate_fail_reasons,
        "issues": issues,
    }
