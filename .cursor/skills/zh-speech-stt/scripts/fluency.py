# -*- coding: utf-8 -*-
"""STT-only fluency on FunASR timestamps. Not used by course scoring."""

from __future__ import annotations

import re
from typing import Any

PUNCT = set("，。？！、；：,.!?;:…—～~·\"'“”‘’（）()【】[]《》<> ")
SENT_END = set("。？！.?!")
PARTICLES = set("的了着过吗呢吧呀嘛哇哦噢哈地得")
FILLERS = {"嗯", "呃", "额", "唔", "哎", "诶", "欸"}
FILLER_PHRASES = (("那", "个", "那", "个"), ("就", "是", "就", "是"))
MID_GAP_MS = 350.0
LONG_COMMA_MS = 500.0
LONG_END_MS = 800.0
SWALLOW_MS = 70.0
PROLONG_MS = 550.0
SPEED_MEAN = 243.0
SPEED_MARGIN = 60.0
SPEED_OK = (SPEED_MEAN - SPEED_MARGIN, SPEED_MEAN + SPEED_MARGIN)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]|[^\s]")


def is_punct(token: str) -> bool:
    return bool(token) and all(ch in PUNCT for ch in token)


def is_speech(token: str) -> bool:
    return bool(token) and not is_punct(token)


def words_from_asr(text: str, timestamp: Any, duration_s: float | None = None) -> list[dict[str, Any]]:
    text = text or ""
    ts: list[list[int]] = []
    for pair in timestamp or []:
        if pair is None or len(pair) < 2:
            continue
        ts.append([int(pair[0]), int(pair[1])])
    tokens = [m.group(0) for m in _TOKEN_RE.finditer(text)]
    if not tokens:
        return []
    speech_idx = [i for i, tok in enumerate(tokens) if is_speech(tok)]
    speech_chars = [ch for ch in text if is_speech(ch)]
    stamp_of: dict[int, tuple[int, int]] = {}
    if ts and len(ts) == len(speech_idx):
        for i, pair in zip(speech_idx, ts):
            stamp_of[i] = (pair[0], pair[1])
    elif ts and len(ts) == len(speech_chars):
        char_i = 0
        for i, tok in enumerate(tokens):
            if not is_speech(tok):
                continue
            stamp_of[i] = (ts[char_i][0], ts[char_i + len(tok) - 1][1])
            char_i += len(tok)
    elif ts:
        n = min(len(speech_idx), len(ts))
        for k in range(n):
            stamp_of[speech_idx[k]] = (ts[k][0], ts[k][1])

    last_end = float(max((end for _, end in stamp_of.values()), default=0.0))
    audio_end = max(last_end, float(duration_s or 0) * 1000.0)
    words: list[dict[str, Any]] = []
    for i, tok in enumerate(tokens):
        if i in stamp_of:
            begin, end = stamp_of[i]
            words.append({"word": tok, "begin": float(begin), "end": float(end)})
            continue
        prev_end = words[-1]["end"] if words else 0.0
        nxt_begin = None
        for j in range(i + 1, len(tokens)):
            if j in stamp_of:
                nxt_begin = float(stamp_of[j][0])
                break
        end = nxt_begin if nxt_begin is not None else audio_end
        words.append({"word": tok, "begin": float(prev_end), "end": float(max(end, prev_end))})
    return words


def clean_text(text: str) -> str:
    if not text:
        return ""
    tokens = [m.group(0) for m in _TOKEN_RE.finditer(text)]
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in FILLERS:
            i += 1
            continue
        skipped = False
        for phrase in FILLER_PHRASES:
            n = len(phrase)
            if i + n <= len(tokens) and tuple(tokens[i : i + n]) == phrase:
                i += n
                skipped = True
                break
        if skipped:
            continue
        if is_speech(tok) and out and out[-1] == tok and tok in PARTICLES:
            i += 1
            continue
        out.append(tok)
        i += 1
    cleaned = "".join(out).strip()
    if cleaned and cleaned[-1] not in SENT_END:
        cleaned += "。"
    return cleaned


def inspect(text: str, timestamp: Any, duration_s: float) -> dict[str, Any]:
    words = words_from_asr(text, timestamp, duration_s)
    speech = [str(w["word"]) for w in words if is_speech(str(w["word"]))]
    duration = duration_s if duration_s > 0 else (
        max((float(w["end"]) for w in words), default=0.0) / 1000.0
    )
    char_count = len(speech)
    cpm = (char_count * 60.0 / duration) if duration > 0 else 0.0
    issues: list[dict[str, Any]] = []
    pause_n = prolong_n = swallow_n = filler_n = repeat_n = 0

    def _dur(w: dict[str, Any]) -> float:
        return max(0.0, float(w["end"]) - float(w["begin"]))

    for i, w in enumerate(words):
        token = str(w["word"])
        begin = float(w["begin"])
        end = float(w["end"])
        dur = _dur(w)
        if i + 1 < len(words):
            nxt = words[i + 1]
            gap = float(nxt["begin"]) - end
            if gap >= MID_GAP_MS and is_speech(token) and is_speech(str(nxt["word"])):
                pause_n += 1
                issues.append({"detail": f"句中空隙 {gap:.0f}ms（{token} → {nxt['word']}）"})
        if token in "，、；,;" and dur > LONG_COMMA_MS:
            pause_n += 1
            issues.append({"detail": f"逗号过长 {dur:.0f}ms"})
        if token in SENT_END and dur >= LONG_END_MS:
            pause_n += 1
            issues.append({"detail": f"句末停顿过长 {dur:.0f}ms"})
        if is_speech(token) and token not in PARTICLES and len(token) == 1:
            if 0 < dur < SWALLOW_MS:
                swallow_n += 1
                issues.append({"detail": f"疑似吞音「{token}」仅 {dur:.0f}ms"})
            if dur > PROLONG_MS:
                prolong_n += 1
                issues.append({"detail": f"拖音「{token}」{dur:.0f}ms"})
        if token in FILLERS:
            filler_n += 1
            issues.append({"detail": f"语气词「{token}」"})

    for i in range(len(speech) - 1):
        if speech[i] == speech[i + 1]:
            repeat_n += 1
            issues.append({"detail": f"连续重复「{speech[i]}{speech[i + 1]}」"})
    for phrase in FILLER_PHRASES:
        n = len(phrase)
        for i in range(len(speech) - n + 1):
            if tuple(speech[i : i + n]) == phrase:
                filler_n += 1
                issues.append({"detail": f"卡顿词「{''.join(phrase)}」"})

    return {
        "cpm": round(cpm, 1),
        "duration": round(duration, 3),
        "speed_in_band": SPEED_OK[0] <= cpm <= SPEED_OK[1],
        "pause_n": pause_n,
        "prolong_n": prolong_n,
        "swallow_n": swallow_n,
        "filler_n": filler_n,
        "repeat_n": repeat_n,
        "issues": issues,
        "text_clean": clean_text(text),
    }
