# -*- coding: utf-8 -*-
"""Compare FunASR text with the timestamp-JSON script (character CER + keywords)."""

from __future__ import annotations

import re
from typing import Any

from analyze_timing import PUNCT

CER_ERROR = 0.08
KEYWORD_ALIASES = {
    "图象": {"图象", "图像"},
    "图像": {"图象", "图像"},
}
GLOSSARY = {
    "函数",
    "变量",
    "坐标",
    "图像",
    "图象",
    "定义域",
    "值域",
    "水平",
    "垂直",
    "拐弯",
    "对应",
    "判断",
    "方程",
    "不等式",
    "斜率",
    "截距",
    "原点",
    "抛物线",
    "直线",
    "曲线",
    "自变量",
    "因变量",
}


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\s+", "", text)
    return "".join(ch for ch in text if ch not in PUNCT)


def cer(ref: str, hyp: str) -> float:
    ref_n = normalize(ref)
    hyp_n = normalize(hyp)
    if not ref_n:
        return 0.0 if not hyp_n else 1.0
    try:
        from rapidfuzz.distance import Levenshtein

        dist = Levenshtein.distance(ref_n, hyp_n)
    except Exception:
        dist = _edit_distance(ref_n, hyp_n)
    return dist / len(ref_n)


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def missing_keywords(ref: str, hyp: str) -> list[str]:
    hyp_n = normalize(hyp)
    ref_raw = ref or ""
    missed: list[str] = []
    for token in re.findall(r"[A-Za-z]+", ref_raw):
        if token.lower() not in hyp_n:
            missed.append(token)
    for word in sorted(GLOSSARY, key=len, reverse=True):
        if word not in ref_raw:
            continue
        aliases = KEYWORD_ALIASES.get(word, {word})
        if not any(alias in (hyp or "") for alias in aliases):
            missed.append(word)
    # de-dup preserve order
    seen = set()
    out = []
    for item in missed:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _base_seq(text: str, *, context: bool) -> list[str]:
    """Initial+final (tone ignored) per hanzi; context=True uses the lexicon reading."""
    from polyphone import expected_readings, is_hanzi, parse_pinyin

    if context:
        return [parse_pinyin(row["pinyin"])[0] for row in expected_readings(text or "")]

    from pypinyin import Style, lazy_pinyin

    chars = [ch for ch in (text or "") if is_hanzi(ch)]
    if not chars:
        return []
    pys = lazy_pinyin("".join(chars), style=Style.TONE3, strict=False)
    return [parse_pinyin(py)[0] for py in pys]


def pinyin_cer(ref: str, hyp: str) -> float:
    """CER over initial+final, so ASR homophones (作/做, 图象/图像) do not count."""
    a = _base_seq(ref, context=True)
    b = _base_seq(hyp, context=False)
    if not a:
        return 0.0 if not b else 1.0
    try:
        from rapidfuzz.distance import Levenshtein

        dist = Levenshtein.distance(a, b)
    except Exception:
        dist = _edit_distance(" ".join(a), " ".join(b))
    return dist / len(a)


def pronunciation_report(ref: str, hyp: str) -> dict[str, Any]:
    char_rate = cer(ref, hyp)
    rate = pinyin_cer(ref, hyp)
    missed = missing_keywords(ref, hyp)
    is_error = rate >= CER_ERROR or bool(missed)
    return {
        "cer": round(rate, 4),
        "cer_pct": round(rate * 100, 1),
        "char_cer": round(char_rate, 4),
        "char_cer_pct": round(char_rate * 100, 1),
        "missing_keywords": missed,
        "is_error": is_error,
    }
