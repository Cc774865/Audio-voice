# -*- coding: utf-8 -*-
"""Pick unambiguous homophone characters so the reference TTS must read the context reading.

edge-tts rejects SSML <phoneme>, so the only way to force a reading is to swap the
polyphone for a common homophone whose *default* reading is the target (same base +
tone). The swap is positional and reversible, so the rest of the pipeline still sees
the original script.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from polyphone import expected_readings, load_lexicon, parse_pinyin

_MAP: dict[str, list[str]] | None = None
MIN_FREQ = 100

# Human-facing examples: same sound, not pinyin. Prefer a clearly different character.
PREFERRED_CHAR = {
    "bian4": "遍",
    "jiao3": "脚",
    "jue2": "绝",
    "lv4": "绿",
    "shuai4": "帅",
    "cheng2": "成",
    "wei2": "围",
    "wei4": "喂",
    "hang2": "航",
    "xing2": "形",
    "zhong4": "众",
    "chong2": "虫",
    "chang2": "常",
    "zhang3": "掌",
    "hai2": "孩",
    "huan2": "环",
    "dao4": "到",
    "dao3": "岛",
}
PREFERRED_WORD = {
    "pian2": "便宜",
}


def _freq() -> dict[str, int]:
    try:
        import jieba

        jieba.initialize()
        return jieba.dt.FREQ
    except Exception:
        return {}


@lru_cache(maxsize=None)
def default_pinyin(ch: str) -> str:
    from pypinyin import Style, pinyin as _py
    from pypinyin.contrib.tone_convert import to_tone3

    try:
        rs = _py(ch, style=Style.TONE3, heteronym=True)
    except Exception:
        return ""
    if not rs or not rs[0]:
        return ""
    return to_tone3(rs[0][0], v_to_u=False)


def _build() -> dict[str, list[str]]:
    """pinyin(tone3) -> non-polyphone chars whose default reading is that pinyin."""
    global _MAP
    if _MAP is not None:
        return _MAP
    from pypinyin import Style, pinyin as _py
    from pypinyin.contrib.tone_convert import to_tone3

    freq = _freq()
    lex = load_lexicon()
    buckets: dict[str, list[str]] = {}
    for cp in range(0x4E00, 0x9FFF + 1):
        ch = chr(cp)
        if ch in lex:
            continue
        try:
            rs = _py(ch, style=Style.TONE3, heteronym=True)
        except Exception:
            continue
        if not rs or not rs[0]:
            continue
        default = to_tone3(rs[0][0], v_to_u=False)
        if not default:
            continue
        buckets.setdefault(default, []).append(ch)
    for key in buckets:
        buckets[key].sort(key=lambda c: -freq.get(c, 0))
    _MAP = buckets
    return _MAP


def example_for_pinyin(pinyin: str, avoid: str | None = None) -> str | None:
    """A common character or word with this reading, for advice (never write bian4)."""
    py = str(pinyin or "").strip()
    if not py:
        return None
    if re.fullmatch(r"[\u4e00-\u9fff]+", py):
        return py
    word = PREFERRED_WORD.get(py)
    if word and word != avoid:
        return word
    pref = PREFERRED_CHAR.get(py)
    if pref and pref != avoid:
        return pref
    freq = _freq()
    ranked: list[str] = []
    seen: set[str] = set()
    for cand in _build().get(py, []):
        if cand == avoid or cand in seen:
            continue
        seen.add(cand)
        ranked.append(cand)
    for ch in load_lexicon():
        if ch == avoid or ch in seen:
            continue
        if default_pinyin(ch) != py:
            continue
        seen.add(ch)
        ranked.append(ch)
    ranked.sort(key=lambda c: -freq.get(c, 0))
    return ranked[0] if ranked else None


def format_reading(pinyin: str, avoid: str | None = None) -> str:
    """Quote a same-sound character; fall back to the raw value if none exists."""
    ex = example_for_pinyin(pinyin, avoid)
    if ex:
        return f"「{ex}」"
    return str(pinyin or "—")


def replacement(char: str, pinyin: str, forbidden: set[str]) -> str | None:
    """A common char whose default reading is exactly pinyin, unused in the sentence."""
    freq = _freq()
    for cand in _build().get(pinyin, []):
        if cand == char or cand in forbidden:
            continue
        if freq.get(cand, 0) < MIN_FREQ:
            return None
        return cand
    return None


def _needs_force(row: dict[str, Any]) -> bool:
    ch = row["char"]
    if ch in {"的", "地", "得"}:
        return True
    if not row.get("polyphone"):
        return False
    py = str(row.get("pinyin") or "")
    default = default_pinyin(ch)
    if not default:
        return True
    return parse_pinyin(py) != parse_pinyin(default)


def plan(script: str) -> dict[str, Any]:
    """Return the TTS surface text plus reversible positional substitutions."""
    chars = list(script or "")
    forbidden = set(c for c in chars if c.strip())
    reuse: dict[tuple[str, str], str] = {}
    subs: list[dict[str, Any]] = []
    unforced: list[dict[str, Any]] = []
    for row in expected_readings(script):
        if not _needs_force(row):
            continue
        idx = int(row["index"])
        ch = row["char"]
        py = str(row.get("pinyin") or "")
        base, _tone = parse_pinyin(py)
        if not base:
            continue
        key = (ch, py)
        repl = reuse.get(key)
        if repl is None:
            repl = replacement(ch, py, forbidden)
            if repl is None:
                unforced.append({"index": idx, "char": ch, "pinyin": py, "why": "no_homophone"})
                continue
            reuse[key] = repl
            forbidden.add(repl)
        chars[idx] = repl
        subs.append({"index": idx, "char": ch, "pinyin": py, "repl": repl})
    return {
        "script": script,
        "text": "".join(chars),
        "subs": subs,
        "unforced": unforced,
    }


def forced_by_index(subs: list[dict[str, Any]] | None) -> dict[int, str]:
    return {int(s["index"]): str(s["pinyin"]) for s in subs or []}


def restore_text(text: str, subs: list[dict[str, Any]] | None) -> str:
    """Map the spoken homophones back to the original characters."""
    out = text or ""
    mapping: dict[str, str] = {}
    for s in subs or []:
        mapping.setdefault(str(s["repl"]), str(s["char"]))
    for repl, orig in mapping.items():
        if repl in out:
            out = out.replace(repl, orig)
    return out
