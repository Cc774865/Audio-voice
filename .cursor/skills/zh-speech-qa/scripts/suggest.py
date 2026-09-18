# -*- coding: utf-8 -*-
"""Turn bucket A / P QA facts into courseware-Agent suggestion records."""

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
        "node_id": None,
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


def build_suggestions(
    errors: list[dict],
    polyphones: list[dict],
    course_id: str = DEFAULT_COURSE_ID,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in errors or []:
        items.extend(suggestions_from_row(row, course_id))
    for row in polyphones or []:
        items.extend(suggestions_from_row(row, course_id))
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
    return str(facts.get("detail") or "")


def render_suggestions_md(suggestions: list[dict[str, Any]]) -> list[str]:
    lines = ["", "### 修改建议（事实，待按错误写方向）"]
    if not suggestions:
        lines.append("无（桶 A / 桶 P 均无）")
        return lines
    cid = suggestions[0].get("course_id") or "—"
    lines.append(
        f"课件 `{cid}`。下列为脚本事实；发给课件 Agent 的建议句由质检按当条错误现写，"
        "不要写替换稿或停顿标记。"
    )
    for i, item in enumerate(suggestions, 1):
        kind = KIND_LABEL.get(item.get("kind") or "", item.get("kind"))
        node = item.get("node_id")
        loc = f"节点 `{node}`" if node else "节点未对上"
        at = " 有at" if item.get("has_at") else ""
        lines.append(
            f"{i}. [桶{item.get('bucket')}·{kind}] `{item.get('clip_id')}` {loc}{at}  "
            f"{fact_line(item)}"
        )
        snippet = _clip((item.get("facts") or {}).get("transcript_ref"), 28)
        if snippet:
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
        "请只改下列口播节点，不要动其它页。无 at 的节点如需拉开间隔，停顿标记只用约 0.4 秒（<#0.4#>），最长不超过 1 秒；禁止 <#2#>、<#3#> 这种超过 1 秒的。有 at 的不要加 <#x#>。不要把「图象」拆开。具体怎么改口播由你决定。",
        "",
    ]
    for i, item in enumerate(ready, 1):
        kind = KIND_LABEL.get(item.get("kind") or "", item.get("kind"))
        clip = item.get("clip_id") or "—"
        node = item.get("node_id")
        if node:
            loc = f"节点 {node}（音频 {clip}）"
        else:
            loc = f"音频 {clip}（节点未对上，请按原稿片段查找）"
            snippet = _clip((item.get("facts") or {}).get("transcript_ref"), 24)
            if snippet:
                loc += f"\n   原稿片段：「{snippet}」"
        advice = str(item.get("advice") or "").strip()
        if item.get("has_at") and AT_NOTE not in advice:
            advice = f"{advice} {AT_NOTE}"
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
    if payload.get("suggestions"):
        items = [dict(x) for x in payload["suggestions"]]
        for item in items:
            item["course_id"] = course_id
        return items
    return build_suggestions(payload.get("errors") or [], payload.get("polyphones") or [], course_id)


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
