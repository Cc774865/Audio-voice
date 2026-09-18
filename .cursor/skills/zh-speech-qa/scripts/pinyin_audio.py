# -*- coding: utf-8 -*-
"""Guess spoken pinyin for each character crop. Used by the review stage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import librosa
import numpy as np

from polyphone import (
    _crop_span,
    _slice,
    estimate_tone,
    format_pinyin,
    is_hanzi,
    load_lexicon,
    parse_pinyin,
    tones_compatible,
)
from ref_tts import DEFAULT_VOICE, synthesize_plain

BASE_MARGIN = 0.02
MIN_COSINE = 0.12
MIN_CROP_MS = 60.0
TONE_CONF = 0.75
CONF_PATH = Path(__file__).resolve().parent.parent / "rules" / "pinyin_confidence.json"
CONF_DEFAULTS = {
    "min_cosine": MIN_COSINE,
    "base_margin": BASE_MARGIN,
    "tone_conf": TONE_CONF,
    "tone_f0_min": 0.30,
    "tone_margin": 0.15,
}
_CONF: dict[str, float] | None = None
PARTICLE_DE = {"地", "的", "得"}
_TPL: dict[str, tuple[np.ndarray | None, np.ndarray | None]] = {}


def confidence() -> dict[str, float]:
    global _CONF
    if _CONF is None:
        data = dict(CONF_DEFAULTS)
        if CONF_PATH.is_file():
            try:
                loaded = json.loads(CONF_PATH.read_text(encoding="utf-8"))
                data.update({k: float(v) for k, v in loaded.items() if isinstance(v, (int, float))})
            except Exception:
                pass
        _CONF = data
    return _CONF


def candidate_pinyins(ch: str) -> list[str]:
    from pypinyin.constants import PINYIN_DICT
    from pypinyin.contrib.tone_convert import to_tone3

    out: list[str] = []
    lex = load_lexicon().get(ch) or []
    if lex:
        for ent in lex:
            py = str(ent.get("pinyin") or "")
            if py and py not in out:
                out.append(py)
        return out
    raw = str(PINYIN_DICT.get(ord(ch), "") or "")
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            t3 = to_tone3(item, v_to_u=False) or item
        except Exception:
            t3 = item
        base, tone = parse_pinyin(t3)
        if not base:
            continue
        py = format_pinyin(base, tone)
        if py not in out:
            out.append(py)
    if not out:
        return out
    first_base = parse_pinyin(out[0])[0]
    return [py for py in out if parse_pinyin(py)[0] == first_base]


def bases_of(cands: list[str]) -> list[tuple[str, str]]:
    """Unique (base, representative_pinyin) in candidate order."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for py in cands:
        base, _ = parse_pinyin(py)
        if not base or base in seen:
            continue
        seen.add(base)
        out.append((base, py))
    return out


def template_phrase(ch: str, pinyin: str) -> str:
    phrases: list[str] = []
    for ent in load_lexicon().get(ch) or []:
        if str(ent.get("pinyin") or "") != pinyin:
            continue
        for phrase in ent.get("phrases") or []:
            text = str(phrase)
            if ch in text and 1 <= len(text) <= 6:
                phrases.append(text)
    if not phrases:
        return ch
    phrases.sort(key=lambda p: (len(p) != 2, len(p)))
    return phrases[0]


def _trim(y: np.ndarray, sr: int) -> np.ndarray:
    if y.size < int(sr * 0.02):
        return y
    try:
        yt, _ = librosa.effects.trim(y, top_db=25)
        if yt.size >= int(sr * 0.03):
            return yt
    except Exception:
        pass
    return y


def _embed(y: np.ndarray, sr: int) -> np.ndarray | None:
    y = _trim(y, sr)
    if y.size < int(sr * 0.03):
        return None
    peak = float(np.max(np.abs(y)) or 1.0)
    y = np.asarray(y, dtype=np.float32) / peak
    n_fft = 512 if y.size < 2048 else 2048
    hop = max(64, n_fft // 4)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, n_fft=n_fft, hop_length=hop)
    parts = [mfcc.mean(axis=1)]
    if mfcc.shape[1] >= 9:
        parts.append(librosa.feature.delta(mfcc).mean(axis=1))
    else:
        parts.append(np.zeros(13, dtype=np.float32))
    vec = np.concatenate(parts)
    n = float(np.linalg.norm(vec) or 1.0)
    return vec / n


def _cosine(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return -1.0
    return float(np.dot(a, b))


def _f0_contour(y: np.ndarray, sr: int, n: int = 16) -> np.ndarray | None:
    """Speaker-normalized pitch contour (semitones, fixed length, mean removed)."""
    from polyphone import _f0_series

    f0 = _f0_series(_trim(y, sr), sr)
    voiced = f0[f0 > 0]
    if voiced.size < 3:
        return None
    semi = 12.0 * np.log2(voiced / float(np.median(voiced)))
    x = np.linspace(0.0, 1.0, semi.size)
    xi = np.linspace(0.0, 1.0, n)
    return np.interp(xi, x, semi)


def _f0_sim(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    if a is None or b is None:
        return None
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    return float(np.dot(a, b) / denom)


def _crop_phrase_char(audio: np.ndarray, sr: int, phrase: str, ch: str) -> np.ndarray:
    y = _trim(audio, sr)
    han = [c for c in phrase if is_hanzi(c)]
    if len(han) <= 1:
        return y
    try:
        i = han.index(ch)
    except ValueError:
        return y
    n = len(han)
    start = int(len(y) * i / n)
    end = int(len(y) * (i + 1) / n)
    crop = y[start:end]
    return crop if crop.size else y


def ensure_template(
    ch: str,
    pinyin: str,
    tpl_dir: Path,
    *,
    voice: str = DEFAULT_VOICE,
    force: bool = False,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Per-reading audio template: (MFCC embedding, normalized F0 contour)."""
    from polyphone import _load_wav

    key = f"{ch}_{pinyin}_{voice}"
    if key in _TPL and not force:
        return _TPL[key]
    crop_path = tpl_dir / f"{key}.npy"
    f0_path = tpl_dir / f"{key}.f0.npy"
    if crop_path.is_file() and not force:
        emb = np.load(crop_path)
        f0 = np.load(f0_path) if f0_path.is_file() else None
        _TPL[key] = (emb, f0)
        return emb, f0
    phrase = template_phrase(ch, pinyin)
    if phrase != ch:
        tts_text, crop_char = phrase, ch
    else:
        from homophones import replacement

        repl = replacement(ch, pinyin, {ch})
        if repl:
            tts_text, crop_char = repl, repl
        else:
            tts_text, crop_char = ch, ch
    wav_path = tpl_dir / f"{key}.mp3"
    try:
        synthesize_plain(tts_text, wav_path, voice=voice, force=force)
    except Exception:
        return None, None
    audio, sr = _load_wav(wav_path)
    crop = _crop_phrase_char(audio, sr, tts_text, crop_char)
    emb = _embed(crop, sr)
    f0 = _f0_contour(crop, sr)
    if emb is None:
        return None, f0
    tpl_dir.mkdir(parents=True, exist_ok=True)
    np.save(crop_path, emb)
    if f0 is not None:
        np.save(f0_path, f0)
    _TPL[key] = (emb, f0)
    return emb, f0


def _unique_readings(cands: list[str]) -> list[str]:
    out: list[str] = []
    for py in cands:
        base, tone = parse_pinyin(py)
        if not base:
            continue
        norm = format_pinyin(base, tone)
        if norm not in out:
            out.append(norm)
    return out


def guess_pinyin(
    crop: np.ndarray,
    sr: int,
    ch: str,
    tpl_dir: Path,
    *,
    voice: str = DEFAULT_VOICE,
    force: bool = False,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    conf = confidence()
    if crop.size < int(sr * MIN_CROP_MS / 1000.0):
        return None
    if expected and not expected.get("lexicon_hit"):
        py = str(expected.get("pinyin") or "")
        cands = [py] if py else candidate_pinyins(ch)
    elif expected and expected.get("candidates"):
        cands = [str(x) for x in expected["candidates"] if x]
    else:
        cands = candidate_pinyins(ch)
    readings = _unique_readings(cands)
    if not readings:
        return None
    multi = len(readings) > 1
    duration_ms = 1000.0 * len(crop) / sr
    if not multi:
        base, tone = parse_pinyin(readings[0])
        return {
            "char": ch,
            "pinyin": readings[0],
            "base": base,
            "tone": tone,
            "tone_conf": 1.0,
            "base_conf": 1.0,
            "best_s": 1.0,
            "multi_base": False,
            "scores": {base: 1.0},
            "base_confident": True,
            "tone_confident": True,
            "confident": True,
            "candidates": list(cands),
        }

    crop_emb = _embed(crop, sr)
    crop_f0 = _f0_contour(crop, sr)
    scored: list[dict[str, Any]] = []
    for pinyin in readings:
        base, tone = parse_pinyin(pinyin)
        emb_t, f0_t = ensure_template(ch, pinyin, tpl_dir, voice=voice, force=force)
        mfcc = _cosine(crop_emb, emb_t)
        f0 = _f0_sim(crop_f0, f0_t)
        scored.append(
            {
                "pinyin": pinyin,
                "base": base,
                "tone": tone,
                "mfcc": mfcc,
                "f0": f0,
                "combined": mfcc + 0.5 * (f0 if f0 is not None else 0.0),
            }
        )
    scored.sort(key=lambda r: r["combined"], reverse=True)
    best = scored[0]
    other_base = [r for r in scored if r["base"] != best["base"]]
    second_base = max((r["mfcc"] for r in other_base), default=-1.0)
    base_conf = best["mfcc"] - second_base
    base_confident = (
        best["mfcc"] >= float(conf["min_cosine"])
        and base_conf >= float(conf.get("base_margin", BASE_MARGIN))
    )
    same_base = [r for r in scored if r["base"] == best["base"]]
    same_base.sort(
        key=lambda r: r["f0"] if r["f0"] is not None else -1.0,
        reverse=True,
    )
    tone_pick = same_base[0]
    tone = tone_pick["tone"]
    f0_best = tone_pick["f0"]
    if len(same_base) == 1:
        tone_confident = True
        f0_margin = 1.0
    elif f0_best is None or same_base[1]["f0"] is None:
        est, tconf = estimate_tone(crop, sr, duration_ms)
        tone = est if est is not None else tone
        tone_confident = est is not None and float(tconf or 0.0) >= float(conf["tone_conf"])
        f0_margin = 0.0
    else:
        f0_margin = float(f0_best) - float(same_base[1]["f0"])
        tone_confident = float(f0_best) >= float(conf["tone_f0_min"]) and f0_margin >= float(
            conf.get("tone_margin", 0.15)
        )
    tone_conf = float(f0_best) if f0_best is not None else 0.0
    score_map: dict[str, float] = {}
    for r in scored:
        score_map[r["base"]] = max(float(r["mfcc"]), score_map.get(r["base"], -1.0))
    return {
        "char": ch,
        "pinyin": format_pinyin(best["base"], tone),
        "base": best["base"],
        "tone": tone,
        "tone_conf": round(tone_conf, 2),
        "base_conf": round(float(base_conf), 3),
        "best_s": round(float(best["mfcc"]), 3),
        "multi_base": multi,
        "scores": {k: round(v, 3) for k, v in score_map.items()},
        "base_confident": bool(base_confident),
        "tone_confident": bool(tone_confident),
        "confident": bool(base_confident and tone_confident),
        "candidates": list(cands),
    }


def known_reading(ch: str, pinyin: str) -> dict[str, Any]:
    """A reference reading we trust because the review TTS was forced to it."""
    base, tone = parse_pinyin(pinyin)
    return {
        "char": ch,
        "pinyin": format_pinyin(base, tone),
        "base": base,
        "tone": tone,
        "tone_conf": 1.0,
        "base_conf": 1.0,
        "best_s": 1.0,
        "multi_base": False,
        "scores": {},
        "base_confident": True,
        "tone_confident": True,
        "confident": True,
        "known": True,
    }


def pinyin_mismatch(
    orig: dict[str, Any],
    ref: dict[str, Any],
    *,
    expected: dict[str, Any] | None = None,
    allow_tone: bool = False,
) -> dict[str, Any] | None:
    """Compare original-audio pinyin with the (verified or known) reference reading.

    Returns a hit dict with kind in {base, tone, unresolved}, or None when they agree.
    """
    ob, rb = orig.get("base"), ref.get("base")
    ch = orig.get("char") or ref.get("char")
    if not ob or not rb:
        return {"kind": "unresolved", "char": ch, "detail": f"「{ch}」拼音识别失败"}
    ref_known = bool(ref.get("known"))
    if ob != rb:
        if not orig.get("base_confident", True):
            return {"kind": "unresolved", "char": ch, "detail": f"「{ch}」原音频声母韵母证据不足"}
        if not ref_known and not ref.get("base_confident", True):
            return {"kind": "unresolved", "char": ch, "detail": f"「{ch}」参考 TTS 声母韵母证据不足"}
        oscores = orig.get("scores") or {}
        rscores = ref.get("scores") or {}
        if ref_known:
            sure = True
        elif ob in oscores and rb in oscores and ob in rscores and rb in rscores:
            orig_gap = float(oscores[ob]) - float(oscores[rb])
            ref_gap = float(rscores[rb]) - float(rscores[ob])
            sure = orig_gap >= 0.02 and ref_gap >= 0.02 and (orig_gap + ref_gap) >= 0.05
        else:
            sure = (
                (not orig.get("multi_base") or orig.get("base_conf", 0) >= 0.02)
                and (not ref.get("multi_base") or ref.get("base_conf", 0) >= 0.02)
            )
        if sure:
            return {
                "kind": "base",
                "char": ch,
                "orig": orig.get("pinyin"),
                "ref": ref.get("pinyin"),
                "detail": f"「{ch}」原音频 {orig.get('pinyin')}，参考 TTS {ref.get('pinyin')}",
            }
        return {"kind": "unresolved", "char": ch, "detail": f"「{ch}」声母韵母差异证据不足"}
    if not allow_tone:
        return None
    if ch in PARTICLE_DE and ob == "de":
        return None
    ot, rt = orig.get("tone"), ref.get("tone")
    if ot is None or rt is None:
        return {"kind": "unresolved", "char": ch, "detail": f"「{ch}」声调识别失败"}
    if not orig.get("tone_confident", False) or not (ref_known or ref.get("tone_confident", False)):
        return {"kind": "unresolved", "char": ch, "detail": f"「{ch}」声调识别不可靠"}
    if tones_compatible(int(ot), int(rt)):
        return None
    if expected is not None:
        want = expected.get("tone")
        if want is not None and not tones_compatible(int(rt), int(want)):
            return None
        if want is not None and tones_compatible(int(ot), int(want)):
            return None
    return {
        "kind": "tone",
        "char": ch,
        "orig": orig.get("pinyin"),
        "ref": ref.get("pinyin"),
        "detail": f"「{ch}」原音频 {orig.get('pinyin')}，参考 TTS {ref.get('pinyin')}",
    }


def align_crops(
    located: list[dict[str, Any]],
    audio: np.ndarray,
    sr: int,
    ch: str,
    loc_i: int,
) -> tuple[int, np.ndarray | None]:
    span = None
    while loc_i < len(located):
        item = located[loc_i]
        loc_i += 1
        if item["char"] == ch:
            span = item
            break
    if span is None:
        return loc_i, None
    begin, end = _crop_span(float(span["begin"]), float(span["end"]), ch)
    return loc_i, _slice(audio, sr, begin, end)
