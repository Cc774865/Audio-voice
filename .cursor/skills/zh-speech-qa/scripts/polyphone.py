# -*- coding: utf-8 -*-
"""Check polyphone readings: script-expected pinyin vs audio tone."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from analyze_timing import PUNCT, is_speech
from asr_local import to_wav16k

LEXICON_PATH = Path(__file__).resolve().parent.parent / "rules" / "polyphones.json"
_LEXICON: dict[str, list[dict[str, Any]]] | None = None

# 结构助词「地」应读 de（轻声/三声）；名词「地」读 di4。
# 轻声 de→di4：要足够长且去声很稳。结构助词「的」只看语境，不用 F0。
DE_TO_DI4_MS = 200.0
DE_TO_DI4_CONF = 0.75
PARTICLE_INSET_MS = 20.0
MIN_CROP_MS = 80.0
DI4_WORDS = {
    "土地", "大地", "地面", "地球", "地点", "地方", "基地", "场地",
    "墓地", "湿地", "陆地", "境地", "阵地", "盆地", "内地", "外地",
    "本地", "异地", "地图", "地址", "地质", "地理", "地震", "地心",
    "地底", "地下", "地上", "地里", "地砖", "地毯", "地线", "地势",
    "地形", "地铁", "地道", "地带", "地层", "地段", "地基", "地价",
    "地皮", "地产", "地租", "地步", "地平", "地核", "地壳", "地磁",
    "地热", "地衣", "地支", "地瓜", "各地", "某地", "田地", "耕地",
    "工地", "驻地", "余地", "平地", "空地", "荒地", "绿地", "菜地",
    "高地", "低地", "洼地", "坡地", "园地", "阵地", "禁地", "圣地",
    "原地", "实地", "阵地",
}
DE_DI4 = {"目的", "标的"}
DE_DI2 = {"的士"}
DE2_WORDS = {
    "得到", "得意", "得当", "得力", "获得", "觉得", "记得", "显得",
    "值得", "难得", "使得", "认得", "懂得", "赢得", "取得", "落得",
    "乐得", "免不了得",
}


def load_lexicon() -> dict[str, list[dict[str, Any]]]:
    global _LEXICON
    if _LEXICON is None:
        if not LEXICON_PATH.is_file():
            _LEXICON = {}
        else:
            data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
            _LEXICON = data.get("chars") or {}
    return _LEXICON


def is_hanzi(ch: str) -> bool:
    return len(ch) == 1 and "\u4e00" <= ch <= "\u9fff"


def _next_hanzi(text: str, i: int) -> str:
    j = i + 1
    while j < len(text):
        if is_hanzi(text[j]):
            return text[j]
        if text[j] not in PUNCT and not text[j].isspace():
            break
        j += 1
    return ""


def _prev_hanzi(text: str, i: int) -> str:
    j = i - 1
    while j >= 0:
        if is_hanzi(text[j]):
            return text[j]
        if text[j] not in PUNCT and not text[j].isspace():
            break
        j -= 1
    return ""


def parse_pinyin(raw: str) -> tuple[str, int]:
    text = (raw or "").strip().lower().replace("ü", "v")
    if not text:
        return "", 5
    tone = 5
    if text[-1].isdigit():
        tone = int(text[-1])
        text = text[:-1]
    return text, tone


def format_pinyin(initial_final: str, tone: int) -> str:
    if tone == 5:
        return initial_final or "de"
    return f"{initial_final}{tone}"


def tones_compatible(expected: int, heard: int) -> bool:
    if expected == heard:
        return True
    return {expected, heard} <= {3, 5}


def lexicon_match(text: str, i: int, ch: str) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    for ent in load_lexicon().get(ch) or []:
        for phrase in ent.get("phrases") or []:
            if ch not in phrase:
                continue
            start = 0
            while True:
                pos = text.find(phrase, start)
                if pos < 0:
                    break
                if pos <= i < pos + len(phrase):
                    if best is None or len(phrase) > best[0]:
                        best = (len(phrase), ent)
                start = pos + 1
    return None if best is None else best[1]


def expected_di(text: str, i: int) -> str:
    prev = _prev_hanzi(text, i)
    nxt = _next_hanzi(text, i)
    if (prev + "地") in DI4_WORDS or ("地" + nxt) in DI4_WORDS:
        return "di4"
    if nxt:
        return "de5"
    return "di4"


def expected_de(text: str, i: int) -> str:
    prev = _prev_hanzi(text, i)
    nxt = _next_hanzi(text, i)
    if (prev + "的") in DE_DI4:
        return "di4"
    if ("的" + nxt) in DE_DI2:
        return "di2"
    return "de5"


def expected_dei(text: str, i: int) -> str:
    prev = _prev_hanzi(text, i)
    nxt = _next_hanzi(text, i)
    if (prev + "得") in DE2_WORDS or ("得" + nxt) in DE2_WORDS:
        return "de2"
    if prev and nxt:
        return "de5"
    return "de2"


def expected_readings(text: str) -> list[dict[str, Any]]:
    from pypinyin import Style, lazy_pinyin
    from pypinyin.constants import PINYIN_DICT

    lex = load_lexicon()
    chars = [(i, ch) for i, ch in enumerate(text or "") if is_hanzi(ch)]
    only = "".join(ch for _, ch in chars)
    pys = lazy_pinyin(only, style=Style.TONE3, strict=False) if only else []
    out: list[dict[str, Any]] = []
    for k, (idx, ch) in enumerate(chars):
        raw_dict = str(PINYIN_DICT.get(ord(ch), "") or "")
        pinyin_cands = [parse_pinyin(x) for x in raw_dict.split(",") if x.strip()]
        pinyin_cands = [(a, b) for a, b in pinyin_cands if a]
        lex_entries = lex.get(ch) or []
        lex_cands = [str(e.get("pinyin") or "") for e in lex_entries if e.get("pinyin")]
        hit = lexicon_match(text, idx, ch)
        if hit:
            py = str(hit.get("pinyin") or "")
        elif ch == "地":
            py = expected_di(text, idx)
        elif ch == "的":
            py = expected_de(text, idx)
        elif ch == "得":
            py = expected_dei(text, idx)
        else:
            py = pys[k] if k < len(pys) else (
                pinyin_cands[0][0] + str(pinyin_cands[0][1]) if pinyin_cands else ""
            )
        base, tone = parse_pinyin(py)
        cand_py = lex_cands or [format_pinyin(a, b) for a, b in {(x, y) for x, y in pinyin_cands}]
        if py and py not in cand_py:
            cand_py = [py, *cand_py]
        tones = {parse_pinyin(c)[1] for c in cand_py if c}
        check_audio = ch in {"地", "的", "得"} or (hit is not None and len(tones) > 1)
        # 结构助词「的」只看语境；疑问「哪」允许 nǎ/něi，不把阳平误配成「哪吒」。
        if ch == "的" and base == "de" and tone in {3, 5}:
            check_audio = False
        elif ch == "哪" and (not hit or "哪吒" not in (hit.get("phrases") or [])):
            check_audio = False
        out.append(
            {
                "index": idx,
                "char": ch,
                "pinyin": format_pinyin(base, tone),
                "base": base,
                "tone": tone,
                "polyphone": ch in lex or ch in {"地", "的", "得"},
                "check_audio": check_audio,
                "lexicon_hit": bool(hit),
                "candidates": cand_py or [format_pinyin(base, tone)],
            }
        )
    return out


def locate_chars(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for w in words or []:
        tok = str(w.get("word") or "")
        if not is_speech(tok):
            continue
        han = [c for c in tok if is_hanzi(c)]
        if not han:
            continue
        begin = float(w.get("begin") or 0)
        end = float(w.get("end") or 0)
        span = max(end - begin, 1.0)
        for i, ch in enumerate(han):
            items.append(
                {
                    "char": ch,
                    "begin": begin + span * i / len(han),
                    "end": begin + span * (i + 1) / len(han),
                }
            )
    return items


def _load_wav(mp3: Path) -> tuple[np.ndarray, int]:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        to_wav16k(mp3, wav)
        data, sr = sf.read(str(wav), always_2d=False)
    if getattr(data, "ndim", 1) > 1:
        data = np.mean(data, axis=1)
    return np.asarray(data, dtype=np.float32), int(sr)


def _slice(y: np.ndarray, sr: int, begin_ms: float, end_ms: float) -> np.ndarray:
    lo = max(0, int((begin_ms / 1000.0) * sr))
    hi = min(len(y), int((end_ms / 1000.0) * sr))
    if hi <= lo:
        return np.zeros(0, dtype=np.float32)
    return y[lo:hi]


def _crop_span(begin_ms: float, end_ms: float, char: str) -> tuple[float, float]:
    """Inset particle timestamps so F0 is not taken from 前/数 etc."""
    if char not in {"地", "的", "得"}:
        return begin_ms, end_ms
    span = max(0.0, end_ms - begin_ms)
    inset = PARTICLE_INSET_MS
    if span - 2 * inset < MIN_CROP_MS:
        inset = max(0.0, (span - MIN_CROP_MS) / 2.0)
    return begin_ms + inset, end_ms - inset


def _f0_series(y: np.ndarray, sr: int) -> np.ndarray:
    if y.size < int(sr * 0.04):
        return np.zeros(0)
    y = y - float(np.mean(y))
    peak = float(np.max(np.abs(y)) or 1.0)
    y = y / peak
    hop = max(40, sr // 200)
    win = max(hop * 2, int(sr * 0.025))
    fmin, fmax = 80.0, 420.0
    tau_min = max(2, int(sr / fmax))
    tau_max = min(win - 2, int(sr / fmin))
    vals: list[float] = []
    for start in range(0, max(1, len(y) - win), hop):
        frame = y[start : start + win]
        if frame.size < win:
            break
        if float(np.sqrt(np.mean(frame * frame))) < 0.02:
            vals.append(0.0)
            continue
        best_tau = 0
        best = 1e9
        for tau in range(tau_min, tau_max):
            a = frame[:-tau]
            b = frame[tau:]
            diff = float(np.mean((a - b) ** 2))
            if diff < best:
                best = diff
                best_tau = tau
        vals.append(sr / best_tau if best_tau else 0.0)
    return np.asarray(vals, dtype=np.float64)


def estimate_tone(y: np.ndarray, sr: int, duration_ms: float) -> tuple[int | None, float]:
    f0 = _f0_series(y, sr)
    voiced = f0[f0 > 0]
    if voiced.size < 3:
        if duration_ms <= 140:
            return 5, 0.35
        return None, 0.0
    x = np.arange(voiced.size, dtype=np.float64)
    slope = float(np.polyfit(x, voiced, 1)[0])
    rng = float(voiced.max() - voiced.min())
    delta = float(voiced[-1] - voiced[0])
    if duration_ms <= 140 and rng < 30:
        return 5, 0.65
    if delta < -18 or slope < -1.2:
        return 4, 0.75 if delta < -25 else 0.55
    if delta > 18 or slope > 1.2:
        return 2, 0.75 if delta > 25 else 0.55
    if voiced.mean() < 140 and rng > 20:
        return 3, 0.5
    if rng < 25:
        return 1, 0.5
    return 3, 0.35


def pinyin_match(expected: dict[str, Any], heard: str) -> bool:
    hbase, htone = parse_pinyin(heard)
    return expected["base"] == hbase and tones_compatible(expected["tone"], htone)


def guess_reading(char: str, expected: dict[str, Any], tone: int | None, duration_ms: float) -> str | None:
    exp_py = expected["pinyin"]
    if char in {"地", "的", "得"}:
        if expected["base"] == "de" and expected["tone"] in {3, 5}:
            # 结构助词「的」只能是 de；轻声下滑很容易被看成去声。
            if char == "的":
                return exp_py
            if tone == 4 and duration_ms >= DE_TO_DI4_MS:
                return "di4"
            return exp_py
        if expected["pinyin"] == "di4":
            if tone in {3, 5} and duration_ms < 140:
                return "de5"
            if tone is None and duration_ms < 120:
                return "de5"
            return "di4"
        if expected["pinyin"] == "di2":
            if tone == 2:
                return "di2"
            if tone == 4 and duration_ms >= DE_TO_DI4_MS:
                return "di4"
            if tone in {3, 5} and duration_ms < 140:
                return "de5"
            return None
        if expected["pinyin"] == "de2":
            if tone == 2:
                return "de2"
            if tone in {3, 5} and duration_ms < 140:
                return "de5"
            return None
    if tone is None:
        return None
    cands = [parse_pinyin(c) for c in expected.get("candidates") or []]
    if any(b == expected["base"] and tones_compatible(t, tone) for b, t in cands):
        return exp_py
    by_tone = [format_pinyin(b, t) for b, t in cands if t == tone]
    if len(set(by_tone)) == 1:
        return by_tone[0]
    return None


def check_polyphones(mp3: Path, transcript: str, words: list[dict[str, Any]]) -> dict[str, Any]:
    expected = [row for row in expected_readings(transcript) if row.get("check_audio")]
    if not expected:
        return {"n_checked": 0, "errors": []}
    located = locate_chars(words)
    audio = None
    sr = 16000
    errors: list[dict[str, Any]] = []
    n_checked = 0
    loc_i = 0
    for row in expected:
        span = None
        while loc_i < len(located):
            item = located[loc_i]
            loc_i += 1
            if item["char"] == row["char"]:
                span = item
                break
        if span is None:
            continue
        n_checked += 1
        crop_begin, crop_end = _crop_span(float(span["begin"]), float(span["end"]), row["char"])
        duration_ms = max(0.0, crop_end - crop_begin)
        if audio is None:
            audio, sr = _load_wav(mp3)
        crop = _slice(audio, sr, crop_begin, crop_end)
        tone, conf = estimate_tone(crop, sr, duration_ms)
        heard = guess_reading(row["char"], row, tone, duration_ms)
        if not heard or pinyin_match(row, heard):
            continue
        if (
            row["char"] in {"地", "得"}
            and row.get("base") == "de"
            and heard == "di4"
            and conf < DE_TO_DI4_CONF
        ):
            continue
        if conf < DE_TO_DI4_CONF:
            continue
        want = row["pinyin"]
        if row["char"] == "地" and row["base"] == "de":
            want = "de（三声/轻声）"
        errors.append(
            {
                "char": row["char"],
                "expected": want,
                "heard": heard,
                "at_ms": round(float(span["begin"]), 1),
                "duration_ms": round(duration_ms, 1),
                "detail": f"多音字「{row['char']}」应读 {want}，听成 {heard}",
            }
        )
    return {"n_checked": n_checked, "errors": errors}
