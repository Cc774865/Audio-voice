---
name: zh-speech-stt
description: >-
  Local FunASR speech-to-text for Chinese/English mp3 files. Transcribes
  audio, checks pause/prolong/swallow/speed on ASR timestamps, and writes a
  rule-cleaned transcript. Use when the user asks to 转写, 语音转文字, 只要mp3,
  识别成文字, or 生成文稿. Do not use for 质检、打分、对照原稿、标注入库.
---

# 语音转文字

只做一件事：给 mp3（或 wav），识别成文字，检查听感是否顺，再出一份去口头禅的优化稿。

**不要**跑质检打分、**不要**对照 json/txt/md 原稿、**不要**写合格/不合格记忆库、**不要**出课件综合分。

必须用项目 `.venv`（Python 3.11）。

## 分流（只走转写）

本 Skill 只做识别成文字。用户说「质检 / 打分 / 对照原稿 / 标注入库」时**不要**用本文件，去 `zh-speech-qa`。

- **不要**运行 `.cursor/skills/zh-speech-qa/scripts/qa_course.py`
- **不要**运行 `qa_one.py` 或 `memory.py`
- 有 json/txt/md 也不要拿来打分，转写仍然只看音频

## 流程

```
- [ ] 1. 确认有 mp3（或 wav），不要求任何文稿
- [ ] 2. 跑 stt_course.py
- [ ] 3. 按脚本 Markdown 回复（原文 + 优化稿 + 流畅摘要）
```

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-stt/scripts/stt_course.py .
```

英文加 `--lang en`。强制重识别加 `--force-asr`。识别缓存在 `*.stt.json`，与质检的 `*.asr.json` 分开。
