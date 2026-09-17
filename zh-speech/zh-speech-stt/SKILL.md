---
name: zh-speech-stt
description: >-
  Local FunASR speech-to-text for Chinese/English mp3 files. Use when the user
  asks to 转写, 语音转文字, 只要mp3, 识别成文字, or 生成文稿. Do not use for
  质检、打分、对照原稿、标注入库.
---

# 语音转文字（通用版）

只做一件事：给 mp3（或 wav），识别成文字，检查听感是否顺，再出一份去口头禅的优化稿。

**不要**跑质检打分、**不要**对照 json/txt/md 原稿、**不要**写合格/不合格记忆库、**不要**出课件综合分。

本目录不依赖 Cursor。必须用 **Python 3.11** 虚拟环境。

## 分流（只走转写）

用户说「质检 / 打分 / 对照原稿 / 标注入库」时**不要**用本文件，去 `zh-speech-qa`。

- **不要**运行 `cli.py qa`
- **不要**运行 `memory` 或 `calibrate`
- 有 json/txt/md 也不要拿来打分，转写仍然只看音频
- 同一请求不要串跑转写和质检

## 流程

```
- [ ] 1. 确认有 mp3（或 wav），不要求任何文稿
- [ ] 2. 跑 cli.py stt
- [ ] 3. 按脚本 Markdown 回复（原文 + 优化稿 + 流畅摘要）
```

在 `zh-speech` 目录：

```bash
python cli.py stt .
```

英文加 `--lang en`。强制重识别加 `--force-asr`。识别缓存在 `*.stt.json`，与质检的 `*.asr.json` 分开。
