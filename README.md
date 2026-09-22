# Audio-voice

课件口播有两条互不调用的流水线。一次请求只走其中一条：转写不管打分，打分不拿转写稿当正确答案。

| 你要做的事 | Skill | 命令 |
|---|---|---|
| 转写、语音转文字、只要 mp3、生成文稿 | `.cursor/skills/zh-speech-stt/` | `stt_course.py` |
| 质检、整课评分、对照原稿、标注入库、复审拼音 | `.cursor/skills/zh-speech-qa/` | `qa_course.py` |

仓库根目录就是 Cursor 项目。必须用 **Python 3.11** 的 `.venv`（不要用 3.14），并安装 ffmpeg。

## 安装

```bash
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -U "funasr==1.4.1" modelscope soundfile pypinyin edge-tts librosa
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/asr_local.py --warmup
```

`--warmup` 只下载中文 `paraformer-zh` 和英文 `paraformer-en`，不装多语种模型。两条线共用这一套模型和虚拟环境，识别缓存分开：转写写 `*.stt.json`，质检写 `*.asr.json`。

## ① 转写

只认音频，不要求 json/txt/md。输出识别原文、去口头禅后的优化稿，以及停顿/拖音/吞音/语速摘要。不出综合分，不写合格库。

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-stt/scripts/stt_course.py .
```

英文加 `--lang en`。强制重识别加 `--force-asr`。

## ② 质检

对照正确稿打分。每句一对同名文件：`foo.mp3` + 正确稿。正确稿优先级：`.json`（带字级时间戳）> `.txt` > `.md`。txt/md 只提供对照文本，停顿/拖音改用 FunASR 时间戳。没有正确稿的 mp3 列入跳过，不会自动改去转写。

默认只输出**一个课件综合分 + 错误列表 + 多音字列表 + 综合判定 + 6 个典型例**。桶 A 错误句全部列出，不占这 6 例。多音字进桶 P 待审，不扣整课错误惩罚。默认会做复审（参考 TTS 逐字拼音，全自动判定）；`--no-review` 关掉，`--strict` 才留待审。

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/qa_course.py .
```

英文加 `--lang en`。强制重识别加 `--force-asr`。JSON 调试加 `--json`。

单句仍可用 `qa_one.py`（仅 json 时间戳，无 FunASR）。

### 分桶（一条句子只进最高优先级）

1. **A 发音错误**（拼音 CER≥8%、缺拉丁字母/课件词、标点连读、或残句）— 全部列出，不占 6 例
2. **P 多音字** — 全部列出，不占 6 例，不扣整课错误惩罚，不自动入库
3. **B 不流畅** — 典型例最多 4 条
4. **C 综合分 < 76** — 再补典型例

### 记忆库

报告发出后：桶 A 错误句立刻写入不合格库（带脚本原因和判定原因），再对 6 个典型例逐条标合格/不合格。

| 库 | 文件 | 何时写 |
|---|---|---|
| 合格 | `.cursor/skills/zh-speech-qa/memory/pass.jsonl` | 典型例标成合格 |
| 不合格 | `.cursor/skills/zh-speech-qa/memory/fail.jsonl` | 桶 A 错误句；典型例标成不合格 |

写入命令见 `.cursor/skills/zh-speech-qa/rules/memory.md`。下次质检默认按分数 / CER / 停顿把最近邻挂在 6 例旁，只给「逻辑」当锚点，不改脚本硬分。转写线不读写这两个库。

不依赖 Cursor 时，把 `zh-speech/` 整夹拷走，用 `python cli.py qa` / `stt`。说明见 `zh-speech/README.md`。

## 校准

单句中位数应落在 76–84。不要重训 FunASR。用记忆库标注跑：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/calibrate.py
```

**每满 60 条**典型例标注才建议改 `LOW_SCORE`、CER 8%、停顿/拖音毫秒、`BASE` / `COMPRESS`。脚本只打印建议，确认后才改 `score.py` / `scoring.md`。问完后跑 `calibrate.py --ack`。
