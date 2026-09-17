---
name: zh-speech-qa
description: >-
  Courseware Chinese/English speech QA with local FunASR. Scores a folder of
  mp3 paired with json, txt, or md scripts, puts pronunciation errors in bucket A
  and polyphones in bucket P, then reports one course score plus error clips,
  polyphone review clips, and six typical examples. After the report, write
  bucket-A errors into the fail memory store with why they failed, then label
  each of the six typical examples pass/fail. Bucket P is review-only: do not
  auto-write fail or change the course error penalty. After labeling, run
  calibrate.py for knob suggestions (LOW_SCORE / CER / pause-ms / BASE) only
  when labels or disagreements are enough; never apply without confirmation.
  Use when the user asks to 质检语音, 整课评分, 打分流畅度, 口播是否流畅, 发音错误,
  标注入库, 对照原稿, 校准阈值, 微调门槛, or to review scored clips. Do not use
  for 转写, 语音转文字, 只要mp3, or 生成文稿.
---

# 中文口播质检（2b）

本地 FunASR（中英）对照原稿，挑出发音错误；多音字另进桶 P 待审；再按不流畅、低分抽样。默认只出**一个综合分 + 错误列表 + 多音字列表 + 6 个典型例**，不要把全部句子打出来。报告发出后：先把桶 A 错误句写入不合格库（带判定原因），再对 6 例逐条标合格/不合格。桶 P 只在逻辑里评，不自动入库、不扣整课错误惩罚。下次质检默认先读两库，把最近邻挂在 6 例旁边，只给「逻辑」当锚点，**不改脚本硬分**。门槛微调走 `calibrate.py`：满 20 条标注或 8 条人机不一致才出建议，**你确认后**才改 `score.py` / `scoring.md`，不重训 FunASR。

必须用项目 `.venv`（Python 3.11），不要用系统 Python 3.14。

## 分流（只走质检）

本 Skill 只做对照打分。用户说「转写 / 语音转文字 / 只要 mp3」时**不要**用本文件，去 `zh-speech-stt`。

- **不要**运行 `.cursor/skills/zh-speech-stt/scripts/stt_course.py`
- 没有 json/txt/md 的 mp3 列入跳过，不要改去转写
- 不要把转写优化稿当作正确稿

## 流程

```
- [ ] 1. 确认目录里是成对的 mp3 + 正确稿（json / txt / md，同名；json 优先）
- [ ] 2. 跑 qa_course.py（FunASR 进桶 A；默认读 pass/fail 两库，近邻挂在 6 例旁）
- [ ] 3. 按脚本输出回复；逻辑对照近邻锚点，只评这几条例子，不改综合分或单句分
- [ ] 4. 把报告中每条桶 A 错误写入 fail 库（source=script，必填 script_reason 与 agent_reason）。桶 P 不自动写。
- [ ] 5. 对 6 个典型例逐条标注入库（见 rules/memory.md）；用户说先不标则跳过
- [ ] 6. 标完后跑 calibrate.py。未达 20 条标注或 8 条人机不一致：只报计数，不改门槛。达到则贴建议，AskQuestion 问是否改；未确认不要改 score.py / scoring.md，也不要改 CER / 停顿毫秒
- [ ] 7. 未要求时不要列出其余句子
```

### 打分命令

在项目根目录：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/qa_course.py .
```

英文口播加 `--lang en`。强制重识别加 `--force-asr`。JSON 调试加 `--json`。不读记忆库加 `--no-memory`。

标注入库后校准（只打印建议）：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/calibrate.py
```

正确稿优先级：同名 `.json`（带字级时间戳）> `.txt` > `.md`。txt/md 只提供对照文本，停顿/拖音改用 FunASR 时间戳，精度低于 json。

单句仍可用 `qa_one.py`（仅 json 时间戳，无 FunASR）。

### 分桶（一条句子只进最高优先级）

1. **A 发音错误**：CER≥8%，或缺拉丁字母/课件关键词，或标点连读（句读标点未停顿且 ASR 粘字），或 gate=fail。**全部列出，不占 6 例。**
2. **P 多音字**：高证据读音不符。**全部列出，不占 6 例，不扣整课错误惩罚，不自动入库。** 规则见 [rules/polyphone.md](rules/polyphone.md)。
3. **B 不流畅**：停顿/拖音/吞音/语速出带。最多取 4 条进典型例。
4. **C 综合分低**：单句分 < 76。

6 例只从非 A、非 P 中挑：先 B（最多 4）→ 再 C → 再从合格句抽低/中/高。没有错误时这 6 条就是给人审的样本。

### 回复模板

直接采用脚本打印的 Markdown。可补一句「逻辑」判断（不计分），只针对列出的错误、多音字和典型例。桶 P 先对照规则看是不是音高误报；不要把 P 改成 A，也不要改综合分。

写「逻辑」时先看每条典型例下面的近邻：合格近邻是正向锚点（这类可放行），不合格近邻加原因是负向锚点（同类要打回）。只写评语，不要改脚本打出的综合分或单句分。两库皆空或没有近邻时跳过对照。

报告发出后立刻把**桶 A 错误句写入 fail 库**，再进入典型例标注入库。错误句不要问用户合不合格；每条必须带脚本原因（`script_reason`）和你认为它错的原因（`agent_reason`）。桶 P 不要自动入库。典型例一次只问一条：AskQuestion 选项为 **合格** / **不合格**；不合格再追问一句原因。写入命令见 [rules/memory.md](rules/memory.md)。

## 规则

- 分桶与口误：[rules/disfluency.md](rules/disfluency.md)
- 多音字（桶 P）：[rules/polyphone.md](rules/polyphone.md)
- 单句与整课打分：[rules/scoring.md](rules/scoring.md)
- 标注入库：[rules/memory.md](rules/memory.md)
- 阈值校准：[scripts/calibrate.py](scripts/calibrate.py)（只出建议，确认后才改文件）
- 多音字知识库：[rules/polyphones.json](rules/polyphones.json)（由 [rules/最全多音字总汇.xls](rules/最全多音字总汇.xls) 编译）
