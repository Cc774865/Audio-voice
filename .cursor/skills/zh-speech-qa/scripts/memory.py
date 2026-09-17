# -*- coding: utf-8 -*-
"""Pass/fail memory stores for bucket-A errors and typical-example labels."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

MEMORY_DIR = Path(
    os.environ.get(
        "ZH_SPEECH_QA_MEMORY",
        str(Path(__file__).resolve().parent.parent / "memory"),
    )
)
PASS_PATH = MEMORY_DIR / "pass.jsonl"
FAIL_PATH = MEMORY_DIR / "fail.jsonl"

Store = Literal["pass", "fail"]
Source = Literal["human", "script"]

PASS_REQUIRED = ("id", "score", "bucket", "transcript_ref")
KEEP = (
    "id",
    "course",
    "score",
    "bucket",
    "cer_pct",
    "cpm",
    "transcript_ref",
    "transcript_asr",
    "script_reason",
    "agent_reason",
    "pause_events",
    "prolong_n",
    "swallow_n",
    "human_reason",
    "source",
    "disagreement",
    "labeled_at",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def store_path(store: Store) -> Path:
    return PASS_PATH if store == "pass" else FAIL_PATH


def load(store: Store) -> list[dict[str, Any]]:
    path = store_path(store)
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def load_all() -> dict[str, list[dict[str, Any]]]:
    return {"pass": load("pass"), "fail": load("fail")}


def disagreement(bucket: str | None, store: Store) -> bool:
    b = (bucket or "").strip().upper()
    if store == "pass":
        return b in {"A", "B", "C"}
    return b in {"", "OK"}


def infer_source(store: Store, rec: dict[str, Any]) -> Source:
    raw = str(rec.get("source") or "").strip().lower()
    if raw in {"human", "script"}:
        return raw  # type: ignore[return-value]
    if store == "fail" and not str(rec.get("human_reason") or "").strip():
        return "script"
    return "human"


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _missing(store: Store, rec: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in PASS_REQUIRED:
        if key == "score":
            if key not in rec or rec[key] is None:
                missing.append(key)
            continue
        if _blank(rec.get(key)):
            missing.append(key)
    if store != "fail":
        return missing
    source = infer_source(store, rec)
    if source == "human" and _blank(rec.get("human_reason")):
        missing.append("human_reason")
    if source == "script":
        if _blank(rec.get("script_reason")):
            missing.append("script_reason")
        if _blank(rec.get("agent_reason")):
            missing.append("agent_reason")
    return missing


def already_stored(store: Store, rec: dict[str, Any], source: Source) -> bool:
    rec_id = str(rec.get("id") or "")
    course = str(rec.get("course") or "")
    for row in load(store):
        if (
            str(row.get("id") or "") == rec_id
            and str(row.get("course") or "") == course
            and str(row.get("source") or "human") == source
        ):
            return True
    return False


def normalize(store: Store, rec: dict[str, Any]) -> dict[str, Any]:
    data = dict(rec)
    if data.get("reason") and not data.get("script_reason"):
        data["script_reason"] = data["reason"]
    source = infer_source(store, data)
    data["source"] = source
    missing = _missing(store, data)
    if missing:
        raise ValueError(f"{store} record missing: {', '.join(missing)}")
    if store == "pass":
        data.pop("human_reason", None)
        data["source"] = "human"
    data["bucket"] = str(data["bucket"]).strip()
    data["disagreement"] = bool(disagreement(str(data["bucket"]), store))
    data["labeled_at"] = data.get("labeled_at") or _utc_now()
    out: dict[str, Any] = {}
    for key in KEEP:
        if key == "human_reason" and store == "pass":
            continue
        if key in data and data[key] is not None:
            out[key] = data[key]
    out["score"] = int(out["score"])
    return out


def append(store: Store, rec: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    row = normalize(store, rec)
    source = row["source"]
    if not force and already_stored(store, row, source):
        row["skipped"] = True
        return row
    path = store_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _read_json_arg(raw: str | None, json_file: str | None) -> dict[str, Any]:
    if json_file:
        return json.loads(Path(json_file).read_text(encoding="utf-8"))
    if raw:
        return json.loads(raw)
    return {}


def _cmd_append(args: argparse.Namespace) -> int:
    rec = _read_json_arg(args.json, args.json_file)
    for key in (
        "id",
        "course",
        "bucket",
        "transcript_ref",
        "transcript_asr",
        "script_reason",
        "agent_reason",
        "human_reason",
        "source",
    ):
        value = getattr(args, key, None)
        if value is not None:
            rec[key] = value
    if args.score is not None:
        rec["score"] = args.score
    if args.cer_pct is not None:
        rec["cer_pct"] = args.cer_pct
    if args.cpm is not None:
        rec["cpm"] = args.cpm
    if args.reason is not None and "script_reason" not in rec:
        rec["script_reason"] = args.reason
    row = append(args.store, rec, force=args.force)
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    data = load_all() if args.store == "all" else {args.store: load(args.store)}
    if args.json:
        print(json.dumps({k: {"n": len(v), "rows": v} for k, v in data.items()}, ensure_ascii=False, indent=2))
        return 0
    for store, rows in data.items():
        print(f"{store}: {len(rows)}")
        for row in rows[-10:]:
            extra = (
                row.get("human_reason")
                or row.get("agent_reason")
                or row.get("script_reason")
                or ""
            )
            src = row.get("source") or "human"
            print(f"  [{src}] {row.get('id')}  {row.get('score')}  {row.get('bucket')}  {extra}")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Pass/fail memory for errors and typical examples")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_append = sub.add_parser("append", help="append one memory record")
    p_append.add_argument("store", choices=("pass", "fail"))
    p_append.add_argument("--json-file", help="UTF-8 JSON object")
    p_append.add_argument("--json", help="JSON object string")
    p_append.add_argument("--id")
    p_append.add_argument("--course")
    p_append.add_argument("--score", type=int)
    p_append.add_argument("--bucket")
    p_append.add_argument("--cer-pct", dest="cer_pct", type=float)
    p_append.add_argument("--cpm", type=float)
    p_append.add_argument("--transcript-ref", dest="transcript_ref")
    p_append.add_argument("--transcript-asr", dest="transcript_asr")
    p_append.add_argument("--reason", help="script reason (alias of script_reason)")
    p_append.add_argument("--script-reason", dest="script_reason")
    p_append.add_argument("--agent-reason", dest="agent_reason")
    p_append.add_argument("--human-reason", dest="human_reason")
    p_append.add_argument("--source", choices=("human", "script"))
    p_append.add_argument("--force", action="store_true", help="append even if id+course+source exists")
    p_append.set_defaults(func=_cmd_append)

    p_list = sub.add_parser("list", help="show stored labels")
    p_list.add_argument("store", nargs="?", default="all", choices=("all", "pass", "fail"))
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
