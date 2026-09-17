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
MID_GAP_MS = 400.0
SHORT_COMMA_MS = 140.0
LONG_COMMA_MS = 500.0
LONG_END_MS = 800.0
SWALLOW_MS = 70.0
DEAD_PUNCT_MS = 60.0
LIAISON_PUNCT = set("，。；？！,.;?!")
PROLONG_MS = 550.0
SPEED_MEAN = 243.0
SPEED_MARGIN = 60.0
SPEED_OK = (SPEED_MEAN - SPEED_MARGIN, SPEED_MEAN + SPEED_MARGIN)


def is_punct(token: str) -> bool:
    return bool(token) and all(ch in PUNCT for ch in token)


def is_speech(token: str) -> bool:
    return bool(token) and not is_punct(token)


def merge_sliced_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse consecutive timestamp slices of the same script word.

    Some courseware JSON splits one token across several time bins but repeats
    the full word string with the same ``offset`` (e.g. 要求 / 应合并). That is
    duration, not a spoken repeat. Different offsets stay separate.
    """
    merged: list[dict[str, Any]] = []
    for raw in words or []:
        word = str(raw.get("word") or "")
        offset = raw.get("offset")
        if (
            merged
            and offset is not None
            and merged[-1].get("offset") == offset
            and str(merged[-1].get("word") or "") == word
            and word
        ):
            prev = merged[-1]
            prev["end"] = raw.get("end", prev.get("end"))
            continue
        merged.append(dict(raw))
    return merged


def load_clip(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    words = merge_sliced_words(data.get("words") or [])
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


def _edge_char(token: str, *, last: bool) -> str:
    chars = [ch for ch in token if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff")]
    if not chars:
        return ""
    return chars[-1] if last else chars[0]


def asr_chars_glued(hyp: str, left: str, right: str) -> bool:
    """True if ASR puts left immediately before right, with no punctuation in between."""
    if not hyp or not left or not right:
        return False
    text = hyp.lower()
    a, b = left.lower(), right.lower()
    start = 0
    while True:
        i = text.find(a, start)
        if i < 0:
            return False
        j = i + len(a)
        while j < len(text) and text[j].isspace():
            j += 1
        if j < len(text) and text.startswith(b, j):
            return True
        start = i + 1


def _neighbor_speech(words: list[dict[str, Any]], index: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    prev = nxt = None
    for j in range(index - 1, -1, -1):
        if is_speech(str(words[j].get("word") or "")):
            prev = words[j]
            break
    for j in range(index + 1, len(words)):
        if is_speech(str(words[j].get("word") or "")):
            nxt = words[j]
            break
    return prev, nxt


def find_punct_liaisons(words: list[dict[str, Any]], hyp: str | None) -> list[dict[str, Any]]:
    """Punctuation that did not create a pause: tiny gap and ASR glued the two sides.

    顿号 between A/B/G is skipped. Need ASR text; no hyp means no flag.
    """
    if not hyp:
        return []
    found: list[dict[str, Any]] = []
    for i, w in enumerate(words or []):
        token = str(w.get("word") or "")
        if token not in LIAISON_PUNCT:
            continue
        prev, nxt = _neighbor_speech(words, i)
        if not prev or not nxt:
            continue
        span = float(nxt.get("begin") or 0) - float(prev.get("end") or 0)
        if span > DEAD_PUNCT_MS:
            continue
        left_tok = str(prev.get("word") or "")
        right_tok = str(nxt.get("word") or "")
        left = _edge_char(left_tok, last=True)
        right = _edge_char(right_tok, last=False)
        if not asr_chars_glued(hyp, left, right):
            continue
        kind = "句号" if token in SENT_END else "逗号"
        found.append(
            {
                "index": i,
                "punct": token,
                "span_ms": round(span, 1),
                "left": left_tok,
                "right": right_tok,
                "at_ms": round(float(w.get("begin") or 0), 2),
                "detail": f"{kind}连读「{left_tok}{token}{right_tok}」空隙 {span:.0f}ms，ASR 粘成「{left}{right}」",
            }
        )
    return found


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]|[^\s]")


def words_from_asr(text: str, timestamp: Any, duration_s: float | None = None) -> list[dict[str, Any]]:
    """Align punctuated ASR text to FunASR per-speech timestamps."""
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


def analyze(path: str | Path) -> dict[str, Any]:
    clip = load_clip(path)
    return analyze_words(clip["words"], clip["duration"], clip_id=clip["id"], path=clip["path"])


def analyze_words(
    words: list[dict[str, Any]],
    duration: float,
    *,
    clip_id: str,
    path: str = "",
    timing_source: str = "json",
    transcript_ref: str | None = None,
    transcript_asr: str | None = None,
) -> dict[str, Any]:
    transcript = transcript_ref if transcript_ref is not None else transcript_of(words)
    speech = speech_tokens(words)
    if duration <= 0 and words:
        duration = max(float(w.get("end") or 0) for w in words) / 1000.0
    char_count = len(speech)
    cpm = (char_count * 60.0 / duration) if duration > 0 else 0.0

    issues: list[dict[str, Any]] = []
    pause_events = 0
    swallow_n = 0
    prolong_n = 0
    filler_n = 0
    repeat_n = 0
    fragment_n = 0
    liaisons = find_punct_liaisons(words, transcript_asr)
    liaison_indexes = {int(item["index"]) for item in liaisons}

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

        if token in COMMA:
            if i in liaison_indexes:
                pass
            elif timing_source != "asr" and dur <= SHORT_COMMA_MS:
                pause_events += 1
                issues.append(
                    {
                        "type": "pause",
                        "at_ms": round(begin, 2),
                        "detail": f"逗号过短 {dur:.0f}ms（须>{SHORT_COMMA_MS:.0f}ms）",
                    }
                )
            elif dur > LONG_COMMA_MS:
                pause_events += 1
                issues.append(
                    {
                        "type": "pause",
                        "at_ms": round(begin, 2),
                        "detail": f"逗号过长 {dur:.0f}ms（>500ms）",
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
            if dur > PROLONG_MS:
                prolong_n += 1
                issues.append(
                    {
                        "type": "prolong",
                        "at_ms": round(begin, 2),
                        "detail": f"拖音「{token}」{dur:.0f}ms（>550ms）",
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

    for item in liaisons:
        issues.append(
            {
                "type": "liaison",
                "at_ms": item.get("at_ms"),
                "detail": item["detail"],
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
        "id": clip_id,
        "path": path,
        "duration": round(duration, 3),
        "transcript_ref": transcript,
        "asr": "skipped",
        "timing_source": timing_source,
        "char_count": char_count,
        "cpm": round(cpm, 1),
        "speed_in_band": speed_in_band,
        "pause_events": pause_events,
        "swallow_n": swallow_n,
        "prolong_n": prolong_n,
        "filler_n": filler_n,
        "repeat_n": repeat_n,
        "fragment_n": fragment_n,
        "liaison_n": len(liaisons),
        "liaison_errors": liaisons,
        "has_question": has_question,
        "weak_question": weak_question,
        "gate_fail_reasons": gate_fail_reasons,
        "issues": issues,
    }
