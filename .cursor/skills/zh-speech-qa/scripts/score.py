# -*- coding: utf-8 -*-
"""Map timing metrics to 0-100 scores. Calibrate BASE/COMPRESS so median ~80."""

from __future__ import annotations

from typing import Any

from analyze_timing import SPEED_OK

# Calibrated on 35 local TTS clips so median lands near 80.
# Only these two knobs should move after a batch re-run.
BASE = 60.0
COMPRESS = 0.70

GATE_CAP = 60


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _speed_score(cpm: float, speed_ok: tuple[float, float] | None = None) -> float:
    lo, hi = speed_ok or SPEED_OK
    if lo <= cpm <= hi:
        return 92.0
    bound = lo if cpm < lo else hi
    steps = abs(cpm - bound) / 20.0
    return _clip(92.0 - 3.0 * steps, 40.0, 100.0)


def _accuracy_score(metrics: dict[str, Any]) -> float:
    score = 92.0
    score -= 4.0 * int(metrics.get("repeat_n") or 0)
    score -= 8.0 * int(metrics.get("fragment_n") or 0)
    score -= 2.0 * int(metrics.get("filler_n") or 0)
    cer = metrics.get("cer")
    if cer is not None:
        score -= min(30.0, float(cer) * 100.0 * 3.0)
    score -= 6.0 * len(metrics.get("missing_keywords") or [])
    score -= 6.0 * len(metrics.get("polyphone_errors") or [])
    return _clip(score, 40.0, 100.0)


def _fluency_score(metrics: dict[str, Any]) -> float:
    score = 90.0
    score -= 8.0 * int(metrics.get("pause_events") or 0)
    score -= 4.0 * int(metrics.get("prolong_n") or 0)
    score -= 3.0 * int(metrics.get("swallow_n") or 0)
    return _clip(score, 40.0, 100.0)


def _pause_score(metrics: dict[str, Any]) -> float:
    n = int(metrics.get("pause_events") or 0)
    return _clip(92.0 - 3.0 * n, 40.0, 100.0)


def _prosody_score(metrics: dict[str, Any]) -> float:
    score = 88.0
    if metrics.get("weak_question"):
        score -= 5.0
    score -= 2.0 * int(metrics.get("swallow_n") or 0)
    score -= 2.0 * int(metrics.get("prolong_n") or 0)
    return _clip(score, 40.0, 100.0)


def score_metrics(metrics: dict[str, Any], speed_ok: tuple[float, float] | None = None) -> dict[str, Any]:
    acc = _accuracy_score(metrics)
    flu = _fluency_score(metrics)
    spd = _speed_score(float(metrics.get("cpm") or 0), speed_ok)
    pau = _pause_score(metrics)
    pro = _prosody_score(metrics)

    raw = 0.30 * acc + 0.25 * flu + 0.15 * spd + 0.15 * pau + 0.15 * pro
    if not metrics.get("gate_fail_reasons") and not metrics.get("issues"):
        raw += 4.0
    raw = _clip(raw)

    final = _clip(BASE + COMPRESS * (raw - BASE))
    gate = "fail" if metrics.get("gate_fail_reasons") else "pass"
    if gate == "fail":
        final = min(final, float(GATE_CAP))

    return {
        "gate": gate,
        "score": int(round(final)),
        "raw": round(raw, 1),
        "subscores": {
            "accuracy": int(round(acc)),
            "fluency": int(round(flu)),
            "speed": int(round(spd)),
            "pause": int(round(pau)),
            "prosody": int(round(pro)),
        },
        "calibration": {"base": BASE, "compress": COMPRESS},
    }
