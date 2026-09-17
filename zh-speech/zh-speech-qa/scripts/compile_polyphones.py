# -*- coding: utf-8 -*-
"""Compile 最全多音字总汇.xls into rules/polyphones.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = Path(__file__).resolve().parent.parent / "rules"
XLS_NAMES = ("最全多音字总汇.xls",)

MARKS = {
    "ā": ("a", 1),
    "á": ("a", 2),
    "ǎ": ("a", 3),
    "à": ("a", 4),
    "ē": ("e", 1),
    "é": ("e", 2),
    "ě": ("e", 3),
    "è": ("e", 4),
    "ī": ("i", 1),
    "í": ("i", 2),
    "ǐ": ("i", 3),
    "ì": ("i", 4),
    "ō": ("o", 1),
    "ó": ("o", 2),
    "ǒ": ("o", 3),
    "ò": ("o", 4),
    "ū": ("u", 1),
    "ú": ("u", 2),
    "ǔ": ("u", 3),
    "ù": ("u", 4),
    "ǖ": ("v", 1),
    "ǘ": ("v", 2),
    "ǚ": ("v", 3),
    "ǜ": ("v", 4),
    "ü": ("v", None),
    "ń": ("n", 2),
    "ň": ("n", 3),
    "ḿ": ("m", 2),
}


def find_xls() -> Path:
    for folder in (ROOT, RULES):
        for name in XLS_NAMES:
            path = folder / name
            if path.is_file():
                return path
    raise FileNotFoundError("最全多音字总汇.xls not found")


def to_tone3(raw: str) -> str:
    s = (raw or "").strip().lower().replace("ɡ", "g").replace("ü", "v")
    if not s:
        return ""
    tone = None
    out: list[str] = []
    for ch in s:
        if ch in MARKS:
            base, marked = MARKS[ch]
            out.append(base)
            if marked is not None:
                tone = marked
        else:
            out.append(ch)
    body = re.sub(r"[^a-z0-9v]", "", "".join(out))
    if not body:
        return ""
    if body[-1].isdigit():
        return body
    return body + str(tone if tone is not None else 5)


def split_phrases(raw: str) -> tuple[list[str], str]:
    text = (raw or "").strip()
    if not text:
        return [], ""
    if "助词" in text or "，" in text or "。" in text:
        parts = [p.strip() for p in re.split(r"\s+", text) if p.strip()]
        phrases = [p for p in parts if "助词" not in p and "，" not in p and "。" not in p and len(p) >= 2]
        note = text if not phrases or "助词" in text else ""
        return phrases, note
    phrases = [p.strip() for p in re.split(r"\s+", text) if len(p.strip()) >= 2]
    return phrases, ""


def compile_book(xls: Path) -> dict:
    import xlrd

    sh = xlrd.open_workbook(str(xls)).sheet_by_index(0)
    chars: dict[str, list[dict]] = {}
    last = {0: None, 5: None}
    for r in range(2, sh.nrows):
        for c0 in (0, 5):
            ch = str(sh.cell_value(r, c0 + 1)).strip()
            py = str(sh.cell_value(r, c0 + 2)).strip()
            words = str(sh.cell_value(r, c0 + 3)).strip()
            if ch:
                last[c0] = ch
                chars.setdefault(ch, [])
            key = last[c0]
            if not key or (not py and not words):
                continue
            pinyin = to_tone3(py)
            if not pinyin:
                continue
            phrases, note = split_phrases(words)
            entry = {"pinyin": pinyin, "display": py, "phrases": phrases}
            if note:
                entry["note"] = note
            chars[key].append(entry)
    return {
        "source": xls.name,
        "n_chars": len(chars),
        "n_readings": sum(len(v) for v in chars.values()),
        "chars": chars,
    }


def main() -> int:
    xls = find_xls()
    data = compile_book(xls)
    out = RULES / "polyphones.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} chars={data['n_chars']} readings={data['n_readings']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
