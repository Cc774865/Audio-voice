# -*- coding: utf-8 -*-
"""Guess spoken pinyin for each character crop. Used by the review stage."""

from __future__ import annotations

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

BASE_MARGIN = 0.03
MIN_COSINE = 0.05
MIN_CROP_MS = 60.0
TONE_CONF = 0.75
PARTICLE_DE = {"地", "的", "得"}
_TPL: dict[str, np.ndarray] = {}


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


def _ssml_phoneme(ch: str, pinyin: str, voice: str) -> str:
    base, tone = parse_pinyin(pinyin)
    ph = "lyu" if base == "lv" else base
    if tone != 5:
        ph = f"{ph}{tone}"
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">'
        f'<voice name="{voice}">'
        f'<phoneme alphabet="sapi" ph="{ph}">{ch}</phoneme>'
        f"</voice></speak>"
    )


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
) -> np.ndarray | None:
    from polyphone import _load_wav

    key = f"{ch}_{pinyin}_{voice}"
    if key in _TPL and not force:
        return _TPL[key]
    crop_path = tpl_dir / f"{key}.npy"
    if crop_path.is_file() and not force:
        emb = np.load(crop_path)
        _TPL[key] = emb
        return emb
    phrase = template_phrase(ch, pinyin)
    wav_path = tpl_dir / f"{key}.mp3"
    text = phrase if phrase != ch else _ssml_phoneme(ch, pinyin, voice)
    try:
        synthesize_plain(text, wav_path, voice=voice, force=force)
    except Exception:
        return None
    audio, sr = _load_wav(wav_path)
    crop = _crop_phrase_char(audio, sr, phrase, ch)
    emb = _embed(crop, sr)
    if emb is None:
        return None
    tpl_dir.mkdir(parents=True, exist_ok=True)
    np.save(crop_path, emb)
    _TPL[key] = emb
    return emb


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
    if crop.size < int(sr * MIN_CROP_MS / 1000.0):
        return None
    if expected and not expected.get("lexicon_hit"):
        py = str(expected.get("pinyin") or "")
        cands = [py] if py else candidate_pinyins(ch)
    elif expected and expected.get("candidates"):
        cands = [str(x) for x in expected["candidates"] if x]
    else:
        cands = candidate_pinyins(ch)
    if not cands:
        return None
    pairs = bases_of(cands)
    duration_ms = 1000.0 * len(crop) / sr
    tone, tconf = estimate_tone(crop, sr, duration_ms)
    multi = len(pairs) > 1
    if not multi:
        base, best_py = pairs[0]
        base_conf = 1.0
        best_s = 1.0
        score_map: dict[str, float] = {base: 1.0}
    else:
        crop_emb = _embed(crop, sr)
        scores: list[tuple[float, str, str]] = []
        for base, py in pairs:
            tpl = ensure_template(ch, py, tpl_dir, voice=voice, force=force)
            scores.append((_cosine(crop_emb, tpl), base, py))
        scores.sort(reverse=True)
        best_s, base, best_py = scores[0]
        second = scores[1][0] if len(scores) > 1 else -1.0
        if best_s < MIN_COSINE:
            return None
        base_conf = max(0.0, best_s - second)
        score_map = {b: float(s) for s, b, _ in scores}
    if tone is None or tconf < TONE_CONF:
        _, used_tone = parse_pinyin(best_py)
        tconf = min(float(tconf or 0.0), 0.4)
    else:
        used_tone = tone
    return {
        "char": ch,
        "pinyin": format_pinyin(base, used_tone if used_tone is not None else 5),
        "base": base,
        "tone": used_tone,
        "tone_conf": round(float(tconf), 2),
        "base_conf": round(float(base_conf), 3),
        "best_s": round(float(best_s), 3),
        "multi_base": multi,
        "scores": {k: round(v, 3) for k, v in score_map.items()},
    }


def pinyin_mismatch(
    orig: dict[str, Any],
    ref: dict[str, Any],
    *,
    expected: dict[str, Any] | None = None,
    allow_tone: bool = False,
) -> dict[str, Any] | None:
    """True when original-audio pinyin and review-TTS pinyin are not the same."""
    ob, rb = orig.get("base"), ref.get("base")
    if not ob or not rb:
        return None
    ch = orig.get("char")
    if ob != rb:
        oscores = orig.get("scores") or {}
        rscores = ref.get("scores") or {}
        gap = 0.0
        if ob in oscores and rb in oscores and ob in rscores and rb in rscores:
            orig_gap = float(oscores[ob]) - float(oscores[rb])
            ref_gap = float(rscores[rb]) - float(rscores[ob])
            gap = orig_gap + ref_gap
            sure = orig_gap >= 0.02 and ref_gap >= 0.02 and gap >= 0.05
        else:
            sure = (
                (not orig.get("multi_base") or orig.get("base_conf", 0) >= BASE_MARGIN)
                and (not ref.get("multi_base") or ref.get("base_conf", 0) >= BASE_MARGIN)
            )
        if sure:
            return {
                "kind": "base",
                "char": ch,
                "orig": orig.get("pinyin"),
                "ref": ref.get("pinyin"),
                "detail": f"「{ch}」原音频 {orig.get('pinyin')}，参考 TTS {ref.get('pinyin')}",
            }
        return None
    if not allow_tone:
        return None
    if ch in PARTICLE_DE and ob == "de":
        return None
    if orig.get("tone_conf", 0) < TONE_CONF or ref.get("tone_conf", 0) < TONE_CONF:
        return None
    ot, rt = orig.get("tone"), ref.get("tone")
    if ot is None or rt is None:
        return None
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
