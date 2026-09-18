# -*- coding: utf-8 -*-
"""Review stage: compare original mp3 with a context-aware reference TTS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from analyze_timing import words_from_asr
from asr_local import transcribe
from cer import cer as char_cer
import json

from homophones import forced_by_index, restore_text
from pinyin_audio import align_crops, guess_pinyin, known_reading, pinyin_mismatch
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
    subs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    poly_errors = poly_errors or []
    forced = forced_by_index(subs)
    flagged = {str(e.get("char") or "") for e in poly_errors if e.get("char")}
    ref_asr = _cached_asr(ref_mp3, model, force)
    ref_raw = ref_asr.get("text") or ""
    ref_text = restore_text(ref_raw, subs)
    duration = float(ref_asr.get("duration_ms") or 0) / 1000.0
    ref_words = words_from_asr(ref_text, ref_asr.get("timestamp"), duration)
    orig_ref_cer = round(char_cer(orig_asr_text or "", ref_text), 4)
    ref_script_cer = round(char_cer(script or "", ref_text), 4)
    rows = expected_readings(script)
    disagree: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
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
        forced_py = forced.get(int(row.get("index", -1)))
        if forced_py is not None:
            ri, _ = align_crops(ref_loc, ref_audio, ref_sr, ch, ri)
            ref_py = known_reading(ch, forced_py)
        else:
            ri, r_crop = align_crops(ref_loc, ref_audio, ref_sr, ch, ri)
            if r_crop is None:
                skipped += 1
                continue
            ref_py = guess_pinyin(r_crop, ref_sr, ch, tpl_dir, voice=voice, expected=row)
            if not ref_py:
                skipped += 1
                continue
        if o_crop is None:
            skipped += 1
            continue
        orig_py = guess_pinyin(o_crop, orig_sr, ch, tpl_dir, voice=voice, expected=row)
        if not orig_py:
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
                or forced_py is not None
            ),
        )
        if not hit:
            continue
        hit["expected"] = row["pinyin"]
        if hit.get("kind") == "unresolved":
            unresolved.append(hit)
        else:
            disagree.append(hit)
    return {
        "skipped": False,
        "engine": "edge-tts",
        "voice": voice,
        "transcript_tts": ref_text,
        "tts_text": None,
        "cer_orig_ref": orig_ref_cer,
        "cer_ref_script": ref_script_cer,
        "cer_orig_ref_pct": round(orig_ref_cer * 100, 1),
        "cer_ref_script_pct": round(ref_script_cer * 100, 1),
        "pinyin_compared": compared,
        "pinyin_skipped": skipped,
        "pinyin_forced": len(forced),
        "pinyin_disagree": disagree,
        "pinyin_unresolved": unresolved,
        "ref_ok": ref_script_cer < REVIEW_CER_ERROR,
    }


def combine_verdict(
    bucket: str,
    review: dict[str, Any] | None,
    poly_errors: list[dict] | None,
    *,
    bucket_a_kind: str = "",
    strict: bool = False,
) -> dict[str, str]:
    """Merge check-stage bucket with review-stage diffs into 错误/不合格/待审/合格.

    Auto mode (default): resolve by source instead of leaving 待审. ASR/reference
    failures pass; a concrete check-stage finding (连读/漏词/gate/发音修正) fails.
    strict=True keeps 待审 for the genuinely undecidable.
    """
    poly_errors = poly_errors or []
    from_pron = any(e.get("source") == "pronunciations" for e in poly_errors)
    from_audio = any((e.get("source") or "audio") == "audio" for e in poly_errors)
    deterministic = bucket_a_kind in {"liaison", "gate", "keyword", "pronunciation"}
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
    unresolved = review.get("pinyin_unresolved") or []
    strong = ref_ok and asr_cer is not None and float(asr_cer) >= REVIEW_CER_ERROR
    mild = ref_ok and asr_cer is not None and float(asr_cer) >= REVIEW_CER_MILD
    pinyin_hit = bool(pinyin_hits)
    uncertain = bool(unresolved) and not pinyin_hit

    if bucket == "A":
        if deterministic:
            if pinyin_hit:
                return {"verdict": "错误", "verdict_reason": "检查阶段确定性问题，且复审拼音指向读错"}
            if strict:
                return {"verdict": "不合格", "verdict_reason": f"检查阶段桶A（{bucket_a_kind}）"}
            return {"verdict": "不合格", "verdict_reason": f"检查阶段确定性问题（{bucket_a_kind}）"}
        if strong or pinyin_hit:
            return {"verdict": "错误", "verdict_reason": "检查阶段桶A，复审与参考 TTS 也不一致"}
        if uncertain and strict:
            return {"verdict": "待审", "verdict_reason": "检查阶段桶A，复审拼音无法判定"}
        return {"verdict": "合格", "verdict_reason": "复审未证实发音错误（疑似 ASR 同音误报）"}

    if (from_audio or from_pron) and pinyin_hit:
        return {"verdict": "错误", "verdict_reason": "读音检查与复审拼音都指向读错"}

    if from_pron:
        if uncertain and not strict:
            return {"verdict": "不合格", "verdict_reason": "发音修正与应读不符，复审未确认但检查阶段已存疑"}
        if strict and uncertain:
            return {"verdict": "待审", "verdict_reason": "发音修正与应读不符，复审拼音无法判定"}
        return {
            "verdict": "不合格",
            "verdict_reason": "发音修正与应读不符，复审未能确认原音频和参考 TTS 拼音不同",
        }

    if from_audio:
        if uncertain and strict:
            return {"verdict": "待审", "verdict_reason": "检查阶段听感多音字不符，复审拼音无法判定"}
        return {"verdict": "不合格", "verdict_reason": "检查阶段听感多音字不符"}

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
        subs=meta.get("subs") or [],
    )
    out["voice"] = meta.get("voice") or voice
    out["tts_text"] = meta.get("tts_text")
    out["ref_mp3"] = str(dest)
    return out
