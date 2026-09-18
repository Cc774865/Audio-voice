# -*- coding: utf-8 -*-
"""Review stage: compare original mp3 with a context-aware reference TTS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from analyze_timing import words_from_asr
from asr_local import transcribe
from cer import cer as char_cer
import json

from pinyin_audio import align_crops, guess_pinyin, pinyin_mismatch
from polyphone import _load_wav, expected_readings, locate_chars, parse_pinyin
from ref_tts import DEFAULT_VOICE, synthesize

REVIEW_CER_ERROR = 0.08
REVIEW_CER_MILD = 0.04
VERDICTS = ("错误", "不合格", "待审", "合格")


def _cached_asr(mp3: Path, model, force: bool) -> dict:
    cache = mp3.with_suffix(".asr.json")
    if cache.exists() and not force:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("text"):
            return data
    result = transcribe(model, mp3)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def compare_audio(
    orig_mp3: Path,
    ref_mp3: Path,
    script: str,
    orig_asr_text: str,
    orig_words: list[dict[str, Any]],
    model,
    tpl_dir: Path,
    *,
    voice: str = DEFAULT_VOICE,
    force: bool = False,
    poly_errors: list[dict] | None = None,
) -> dict[str, Any]:
    poly_errors = poly_errors or []
    flagged = {str(e.get("char") or "") for e in poly_errors if e.get("char")}
    ref_asr = _cached_asr(ref_mp3, model, force)
    ref_text = ref_asr.get("text") or ""
    duration = float(ref_asr.get("duration_ms") or 0) / 1000.0
    ref_words = words_from_asr(ref_text, ref_asr.get("timestamp"), duration)
    orig_ref_cer = round(char_cer(orig_asr_text or "", ref_text), 4)
    ref_script_cer = round(char_cer(script or "", ref_text), 4)
    rows = expected_readings(script)
    disagree: list[dict[str, Any]] = []
    compared = 0
    skipped = 0
    orig_audio = ref_audio = None
    orig_sr = ref_sr = 0
    orig_loc: list[dict[str, Any]] = []
    ref_loc: list[dict[str, Any]] = []
    oi = ri = 0
    if rows:
        orig_audio, orig_sr = _load_wav(orig_mp3)
        ref_audio, ref_sr = _load_wav(ref_mp3)
        orig_loc = locate_chars(orig_words)
        ref_loc = locate_chars(ref_words)
    for row in rows:
        ch = row["char"]
        oi, o_crop = align_crops(orig_loc, orig_audio, orig_sr, ch, oi)
        ri, r_crop = align_crops(ref_loc, ref_audio, ref_sr, ch, ri)
        if o_crop is None or r_crop is None:
            skipped += 1
            continue
        orig_py = guess_pinyin(o_crop, orig_sr, ch, tpl_dir, voice=voice, expected=row)
        ref_py = guess_pinyin(r_crop, ref_sr, ch, tpl_dir, voice=voice, expected=row)
        if not orig_py or not ref_py:
            skipped += 1
            continue
        compared += 1
        tones = {parse_pinyin(c)[1] for c in (row.get("candidates") or []) if c}
        hit = pinyin_mismatch(
            orig_py,
            ref_py,
            expected=row,
            allow_tone=bool(
                row.get("check_audio")
                or ch in flagged
                or (row.get("lexicon_hit") and len(tones) > 1)
            ),
        )
        if not hit:
            continue
        hit["expected"] = row["pinyin"]
        disagree.append(hit)
    return {
        "skipped": False,
        "engine": "edge-tts",
        "voice": voice,
        "transcript_tts": ref_text,
        "cer_orig_ref": orig_ref_cer,
        "cer_ref_script": ref_script_cer,
        "cer_orig_ref_pct": round(orig_ref_cer * 100, 1),
        "cer_ref_script_pct": round(ref_script_cer * 100, 1),
        "pinyin_compared": compared,
        "pinyin_skipped": skipped,
        "pinyin_disagree": disagree,
        "ref_ok": ref_script_cer < REVIEW_CER_ERROR,
    }


def combine_verdict(bucket: str, review: dict[str, Any] | None, poly_errors: list[dict] | None) -> dict[str, str]:
    """Merge check-stage bucket with review-stage diffs into 错误/不合格/待审/合格."""
    poly_errors = poly_errors or []
    from_pron = any(e.get("source") == "pronunciations" for e in poly_errors)
    from_audio = any((e.get("source") or "audio") == "audio" for e in poly_errors)
    if not review or review.get("skipped"):
        if bucket == "A":
            return {"verdict": "错误", "verdict_reason": "检查阶段桶A，复审未跑"}
        if bucket == "P":
            return {"verdict": "不合格", "verdict_reason": "检查阶段桶P，复审未跑"}
        if bucket in {"B", "C"}:
            return {"verdict": "不合格", "verdict_reason": f"检查阶段桶{bucket}，复审未跑"}
        return {"verdict": "合格", "verdict_reason": "检查阶段合格，复审未跑"}

    asr_cer = review.get("cer_orig_ref")
    ref_ok = bool(review.get("ref_ok"))
    pinyin_hits = review.get("pinyin_disagree") or review.get("tone_disagree") or []
    strong = ref_ok and asr_cer is not None and float(asr_cer) >= REVIEW_CER_ERROR
    mild = ref_ok and asr_cer is not None and float(asr_cer) >= REVIEW_CER_MILD
    pinyin_hit = bool(pinyin_hits)

    if bucket == "A":
        if strong or pinyin_hit or mild:
            return {"verdict": "错误", "verdict_reason": "检查阶段桶A，复审与参考 TTS 也不一致"}
        return {"verdict": "待审", "verdict_reason": "检查阶段 CER 高，但原音频和参考 TTS 几乎相同"}

    if (from_audio or from_pron) and pinyin_hit:
        return {"verdict": "错误", "verdict_reason": "读音检查与复审拼音都指向读错"}

    if from_pron and not pinyin_hit:
        return {
            "verdict": "不合格",
            "verdict_reason": "发音修正与应读不符，复审未能确认原音频和参考 TTS 拼音不同",
        }

    if from_audio:
        return {"verdict": "不合格", "verdict_reason": "检查阶段听感多音字不符，复审未交叉确认"}

    if strong:
        why = "复审：原音频和参考 TTS 识别差 ≥8%，参考贴原稿"
        if bucket in {"B", "C"}:
            return {"verdict": "不合格", "verdict_reason": f"检查阶段桶{bucket}；{why}"}
        return {"verdict": "不合格", "verdict_reason": why}

    if bucket in {"B", "C"} or mild or pinyin_hit:
        bits = []
        if bucket in {"B", "C"}:
            bits.append(f"检查阶段桶{bucket}")
        if mild:
            bits.append("复审原/参识别略有差别")
        if pinyin_hit:
            bits.append("复审拼音不一致")
        return {"verdict": "不合格", "verdict_reason": "；".join(bits) or "不合格"}

    return {"verdict": "合格", "verdict_reason": "检查与复审均未发现稳定差异"}


def review_clip(
    orig_mp3: Path,
    script: str,
    orig_asr_text: str,
    orig_words: list[dict[str, Any]],
    model,
    ref_dir: Path,
    *,
    voice: str = DEFAULT_VOICE,
    force_asr: bool = False,
    force_tts: bool = False,
    poly_errors: list[dict] | None = None,
) -> dict[str, Any]:
    dest = ref_dir / f"{orig_mp3.stem}.mp3"
    try:
        meta = synthesize(script, dest, voice=voice, force=force_tts)
    except Exception as exc:
        return {
            "skipped": True,
            "skip_reason": f"参考 TTS 失败：{type(exc).__name__}: {exc}",
            "engine": "edge-tts",
            "voice": voice,
            "pinyin_disagree": [],
            "pinyin_compared": 0,
            "pinyin_skipped": 0,
        }
    out = compare_audio(
        orig_mp3,
        dest,
        script,
        orig_asr_text,
        orig_words,
        model,
        ref_dir / ".pinyin-tpl",
        voice=voice,
        force=force_asr,
        poly_errors=poly_errors,
    )
    out["voice"] = meta.get("voice") or voice
    out["ref_mp3"] = str(dest)
    return out
