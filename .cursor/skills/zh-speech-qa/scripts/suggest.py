# -*- coding: utf-8 -*-
"""Turn bucket A / P plus typical-example QA facts into Agent suggestion records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from cer import CER_ERROR
from homophones import format_reading
from jx_agent import JxError, fetch_courseware, get_token

DEFAULT_COURSE_ID = ""
KIND_LABEL = {
    "liaison": "连读",
    "cer": "发音",
    "keyword": "缺词",
    "gate": "结构",
    "polyphone": "多音字",
    "fluency": "不流畅",
    "low_score": "分低",
    "typical": "典型例",
}
AUDIO_KEYS = {
    "src",
    "url",
    "audio",
    "audioSrc",
    "audioUrl",
    "audio_url",
    "mp3",
    "file",
    "path",
    "filename",
    "fileName",
}
TEXT_KEYS = {
    "text",
    "content",
    "speech",
    "voiceover",
    "caption",
    "script",
    "say",
    "oral",
    "tts",
    "narration",
    "plainText",
    "plain_text",
}
AT_NOTE = "不要加停顿标记，用重做 TTS 拉开或收紧间隔。"
# `<#x#>` 的 x 是秒：0.3=0.3s，1=1s。按当前空隙选，不要一律 0.4，且不超过 1。
PAUSE_HEADER = (
    "请只改下列口播节点，不要动其它页。"
    "停顿标记的数字是秒：<#0.3#> 就是 0.3 秒，<#1#> 就是 1 秒；最长 1 秒，禁止 <#2#>、<#3#>。"
    "每条里的秒数已按当前间隔选好，不要改成同一个数。"
    "有 at 的不要加 <#x#>。不要把「图象」拆开。"
)


def pause_seconds(span_ms: float | None, *, purpose: str = "comma") -> float:
    """Seconds for `<#x#>`. x is seconds (0.3 = 0.3s, 1 = 1s), capped at 1."""
    if purpose == "letter":
        return 0.1
    if span_ms is None:
        return 0.3
    gap = float(span_ms)
    if gap <= 80:
        return 0.1
    if gap <= 160:
        return 0.3
    if gap <= 250:
        return 0.4
    return 0.5


def pause_mark(span_ms: float | None, *, purpose: str = "comma") -> str:
    sec = min(pause_seconds(span_ms, purpose=purpose), 1.0)
    return f"<#{sec:g}#>"


def _clip(text: str | None, n: int = 12) -> str:
    raw = str(text or "").replace("\n", "").strip()
    return raw if len(raw) <= n else raw[:n]


def _item(row: dict, course_id: str, bucket: str, kind: str, facts: dict[str, Any]) -> dict[str, Any]:
    facts = dict(facts)
    facts.setdefault("transcript_ref", row.get("transcript_ref") or "")
    facts.setdefault("transcript_asr", row.get("transcript_asr") or "")
    return {
        "course_id": str(course_id),
        "clip_id": row.get("id"),
        "bucket": bucket,
        "kind": kind,
        "node_id": row.get("node_id"),
        "has_at": None,
        "facts": facts,
        "advice": None,
    }


def suggestions_from_row(row: dict, course_id: str) -> list[dict[str, Any]]:
    bucket = row.get("bucket")
    out: list[dict[str, Any]] = []
    if bucket == "A":
        for err in row.get("liaison_errors") or []:
            out.append(
                _item(
                    row,
                    course_id,
                    "A",
                    "liaison",
                    {
                        "left": err.get("left"),
                        "right": err.get("right"),
                        "punct": err.get("punct"),
                        "span_ms": err.get("span_ms"),
                        "at_ms": err.get("at_ms"),
                        "detail": err.get("detail"),
                    },
                )
            )
        missing = list(row.get("missing_keywords") or [])
        if missing:
            out.append(_item(row, course_id, "A", "keyword", {"missing_keywords": missing}))
        cer = row.get("cer")
        cer_pct = row.get("cer_pct")
        if cer is None and cer_pct is not None:
            cer = float(cer_pct) / 100.0
        if cer is not None and float(cer) >= CER_ERROR:
            out.append(_item(row, course_id, "A", "cer", {"cer_pct": cer_pct}))
        gate = list(row.get("gate_fail_reasons") or [])
        if gate:
            out.append(_item(row, course_id, "A", "gate", {"reasons": gate}))
        return out
    if bucket == "P":
        for err in row.get("polyphone_errors") or []:
            char = str(err.get("char") or "")
            expected = str(err.get("expected") or "")
            heard = str(err.get("heard") or "")
            want_zh = format_reading(expected, char or None)
            heard_zh = format_reading(heard, char or None)
            item = _item(
                row,
                course_id,
                "P",
                "polyphone",
                {
                    "char": char,
                    "expected": expected,
                    "heard": heard,
                    "expected_zh": want_zh,
                    "heard_zh": heard_zh,
                    "at_ms": err.get("at_ms"),
                    "duration_ms": err.get("duration_ms"),
                    "source": err.get("source"),
                    "detail": err.get("detail"),
                },
            )
            item["advice"] = (
                f"「{char}」应读{want_zh}，不要读成{heard_zh}。"
                "只改口播读音，不要改汉字。"
            )
            out.append(item)
        return out
    kind = {"B": "fluency", "C": "low_score"}.get(bucket, "typical")
    return [
        _item(
            row,
            course_id,
            bucket or "ok",
            kind,
            {
                "reason": row.get("reason"),
                "pause_events": row.get("pause_events"),
                "verdict": row.get("verdict"),
                "detail": row.get("reason") or "",
            },
        )
    ]


def build_suggestions(
    errors: list[dict],
    polyphones: list[dict],
    course_id: str = DEFAULT_COURSE_ID,
    typical: list[dict] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for row in list(errors or []) + list(polyphones or []) + list(typical or []):
        for item in suggestions_from_row(row, course_id):
            key = (item.get("clip_id"), item.get("kind"))
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def fact_line(item: dict[str, Any]) -> str:
    facts = item.get("facts") or {}
    kind = item.get("kind")
    if kind == "liaison":
        left = facts.get("left") or ""
        punct = facts.get("punct") or ""
        right = facts.get("right") or ""
        span = facts.get("span_ms")
        span_s = f"{span}ms" if span is not None else "—"
        return f"「{left}{punct}{right}」空隙 {span_s}"
    if kind == "polyphone":
        char = facts.get("char") or ""
        want = format_reading(str(facts.get("expected") or ""), char or None)
        heard = format_reading(str(facts.get("heard") or ""), char or None)
        if facts.get("source") == "pronunciations":
            return f"「{char}」应读{want}，发音修正写成{heard}"
        return f"「{char}」应读{want}，听成{heard}"
    if kind == "keyword":
        words = facts.get("missing_keywords") or []
        return "缺 " + "、".join(str(x) for x in words)
    if kind == "cer":
        pct = facts.get("cer_pct")
        return f"CER {pct}%" if pct is not None else "CER 过高"
    if kind == "gate":
        reasons = facts.get("reasons") or []
        return "；".join(str(x) for x in reasons) or "残句或重复"
    if kind in {"fluency", "low_score", "typical"}:
        return str(facts.get("reason") or facts.get("detail") or "")
    return str(facts.get("detail") or "")


def render_suggestions_md(suggestions: list[dict[str, Any]]) -> list[str]:
    lines = ["", "### 修改建议（错误 + 6 个典型例）"]
    if not suggestions:
        lines.append("无")
        return lines
    cid = suggestions[0].get("course_id") or "—"
    lines.append(
        f"课件 `{cid}`。错误和 6 个典型例都会写出建议；是否发给课件 Agent 由你决定。"
        "建议句由质检按当条现写，不要写替换稿或停顿标记。"
    )
    for i, item in enumerate(suggestions, 1):
        kind = KIND_LABEL.get(item.get("kind") or "", item.get("kind"))
        node = item.get("node_id")
        snippet = _clip((item.get("facts") or {}).get("transcript_ref"), 28)
        loc = f"节点 `{node}`" if node else (f"「{snippet}」" if snippet else "节点未对上")
        at = " 有at" if item.get("has_at") else ""
        lines.append(
            f"{i}. [桶{item.get('bucket')}·{kind}] {loc}{at}  "
            f"{fact_line(item)}"
        )
        if snippet and node:
            lines.append(f"   原稿「{snippet}」")
        if item.get("advice"):
            lines.append(f"   建议：{item['advice']}")
    return lines


def render_agent_message(course_id: str, suggestions: list[dict[str, Any]]) -> str:
    if not suggestions:
        raise ValueError("没有建议，不能生成发给课件 Agent 的消息")
    missing = [x for x in suggestions if not str(x.get("advice") or "").strip()]
    if missing:
        raise ValueError(f"{len(missing)} 条建议还没有 advice，不能生成发给课件 Agent 的消息")
    ready = suggestions
    lines = [
        f"课件ID: {course_id}",
        PAUSE_HEADER,
        "",
    ]
    for i, item in enumerate(ready, 1):
        kind = KIND_LABEL.get(item.get("kind") or "", item.get("kind"))
        node = item.get("node_id")
        snippet = _clip((item.get("facts") or {}).get("transcript_ref"), 24)
        if node:
            loc = f"节点 {node}"
            if snippet:
                loc += f"\n   原稿：「{snippet}」"
        else:
            loc = "节点未对上，请按原稿片段查找"
            if snippet:
                loc += f"\n   原稿片段：「{snippet}」"
        advice = str(item.get("advice") or "").strip()
        if item.get("has_at") and AT_NOTE not in advice:
            advice = f"{advice} {AT_NOTE}"
        elif (
            not item.get("has_at")
            and item.get("kind") in {"liaison", "fluency"}
            and "<#" not in advice
        ):
            facts = item.get("facts") or {}
            mark = pause_mark(facts.get("span_ms"), purpose="comma")
            advice = f"{advice.rstrip('。')}。写入 {mark}，不要用破折号或空格代替。"
        lines.append(f"{i}. {loc} [桶{item.get('bucket')}·{kind}]")
        lines.append(f"   {advice}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _node_id(obj: dict) -> str | None:
    for key in ("id", "nodeId", "uuid", "key"):
        val = obj.get(key)
        if val is not None and str(val).strip():
            return str(val)
    return None


def _has_at(obj: dict) -> bool:
    at = obj.get("at")
    if at:
        return True
    words = obj.get("words")
    if isinstance(words, list) and any(isinstance(w, dict) and ("at" in w or "begin" in w) for w in words):
        return True
    return False


def iter_nodes(courseware: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            nid = _node_id(obj)
            texts: list[str] = []
            blobs: list[str] = []
            if nid:
                blobs.append(nid)
            for key, val in obj.items():
                if isinstance(val, str):
                    blobs.append(val)
                    if key in TEXT_KEYS or key in AUDIO_KEYS:
                        texts.append(val)
                elif key in AUDIO_KEYS:
                    blobs.append(_stringify(val))
            interesting = nid or any(k in obj for k in AUDIO_KEYS) or any(k in obj for k in TEXT_KEYS)
            if interesting:
                audio = None
                for key in AUDIO_KEYS:
                    val = obj.get(key)
                    if isinstance(val, str) and val.strip():
                        audio = Path(val.strip()).stem
                        break
                prons = obj.get("pronunciations")
                nodes.append(
                    {
                        "id": nid,
                        "has_at": _has_at(obj),
                        "text": " ".join(texts),
                        "blob": " ".join(blobs).lower(),
                        "audio": audio,
                        "pronunciations": list(prons) if isinstance(prons, list) else [],
                    }
                )
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(courseware)
    return nodes


def locate_node(courseware: Any, clip_id: str | None, transcript_ref: str | None) -> dict[str, Any] | None:
    needle = str(clip_id or "").strip().lower()
    snippet = _clip(transcript_ref, 12)
    best: dict[str, Any] | None = None
    best_score = 0
    for node in iter_nodes(courseware):
        score = 0
        blob = node.get("blob") or ""
        text = node.get("text") or ""
        nid = str(node.get("id") or "").lower()
        if needle:
            if nid == needle:
                score += 80
            if needle in blob:
                score += 100
        if snippet and snippet in (text or blob):
            score += 40
        if score > best_score:
            best_score = score
            best = node
    if best_score <= 0:
        return None
    return best


def locate_suggestions(suggestions: list[dict[str, Any]], courseware: Any) -> list[dict[str, Any]]:
    out = []
    for item in suggestions:
        facts = item.get("facts") or {}
        hit = locate_node(courseware, item.get("clip_id"), facts.get("transcript_ref"))
        row = dict(item)
        if hit:
            row["node_id"] = hit.get("id")
            row["has_at"] = bool(hit.get("has_at"))
        out.append(row)
    return out


def clip_pronunciations(courseware: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for node in iter_nodes(courseware):
        audio = node.get("audio")
        prons = [str(x) for x in (node.get("pronunciations") or []) if str(x).strip()]
        if audio and prons:
            out[str(audio)] = prons
    return out


def load_payload(path: str) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"suggestions": raw}
    if not isinstance(raw, dict):
        raise ValueError("JSON must be an object or a suggestion list")
    return raw


def suggestions_from_payload(payload: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    if payload.get("errors") or payload.get("polyphones") or payload.get("typical"):
        items = build_suggestions(
            payload.get("errors") or [],
            payload.get("polyphones") or [],
            course_id,
            payload.get("typical") or [],
        )
        old = {
            (x.get("clip_id"), x.get("kind")): x
            for x in payload.get("suggestions") or []
        }
        for item in items:
            prev = old.get((item.get("clip_id"), item.get("kind")))
            if not prev:
                continue
            if prev.get("advice") and not item.get("advice"):
                item["advice"] = prev["advice"]
            if prev.get("node_id") and not item.get("node_id"):
                item["node_id"] = prev["node_id"]
                item["has_at"] = prev.get("has_at")
        return items
    if payload.get("suggestions"):
        items = [dict(x) for x in payload["suggestions"]]
        for item in items:
            item["course_id"] = course_id
        return items
    return []


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build courseware-Agent suggestions from QA JSON")
    parser.add_argument("--from-json", required=True, help="qa_course --json output, or suggestions JSON")
    parser.add_argument("--course-id", default=DEFAULT_COURSE_ID, help="测试环境课件 ID；locate/发送时必填")
    parser.add_argument("--locate", action="store_true", help="GET courseware and fill node_id")
    parser.add_argument("--print-message", action="store_true", help="print Agent message; advice must be filled")
    parser.add_argument("--out", help="write suggestions JSON")
    parser.add_argument("--token", help="jx_token; default env JX_TOKEN")
    args = parser.parse_args()
    payload = load_payload(args.from_json)
    course_id = str(args.course_id)
    items = suggestions_from_payload(payload, course_id)
    locate_error = None
    if args.locate:
        try:
            token = get_token(args.token)
            courseware = fetch_courseware(course_id, token)
            items = locate_suggestions(items, courseware)
        except JxError as exc:
            locate_error = {"status": exc.status, "error": exc.body}
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            return 1
    result = {
        "course_id": course_id,
        "suggestions": items,
        "locate_error": locate_error,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.print_message:
        if locate_error:
            print(json.dumps({"ok": False, "locate_error": locate_error}, ensure_ascii=False), file=sys.stderr)
            return 2
        try:
            print(render_agent_message(course_id, items), end="")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if locate_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
