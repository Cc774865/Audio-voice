---
name: zh-speech-qa
description: >-
  Courseware Chinese/English speech QA with local FunASR. Scores a folder of
  mp3 paired with json, txt, or md scripts, puts pronunciation errors in bucket A
  and polyphones in bucket P, then reviews original vs context-aware TTS by
  comparing per-character pinyin. Reports one course score plus error clips,
  polyphone review clips, combined verdicts, and six typical examples. After
  the report, write bucket-A errors into the fail memory store with why they
  failed, then label each of the six typical examples pass/fail. Bucket P is
  review-only: do not auto-write fail or change the course error penalty.
  After labeling, run calibrate.py for knob suggestions (LOW_SCORE / CER /
  pause-ms / BASE) only when labels or disagreements are enough; never apply
  without confirmation.
  Use when the user asks to 质检语音, 整课评分, 打分流畅度, 口播是否流畅, 发音错误,
  标注入库, 对照原稿, 复审拼音, 校准阈值, 微调门槛, or to review scored clips.
  Do not use for 转写, 语音转文字, 只要mp3, or 生成文稿.
---

# 中文口播质检（通用版）

对照原稿打分。默认再跑复审（参考 TTS vs 原音频逐字拼音）。默认只出**一个综合分 + 错误列表 + 多音字列表 + 综合判定 + 6 个典型例**。近邻锚点只给「逻辑」用，不改脚本硬分。不重训 FunASR。

本目录不依赖 Cursor。必须用 **Python 3.11** 虚拟环境。

## 分流（只走质检）

用户说「转写 / 语音转文字 / 只要 mp3」时**不要**用本文件，去 `zh-speech-stt`。

- **不要**运行 `cli.py stt`
- 没有 json/txt/md 的 mp3 列入跳过，不要改去转写
- 不要把转写优化稿当作正确稿
- 同一请求不要串跑转写和质检

## 流程

```
- [ ] 1. 确认目录里是成对的 mp3 + 正确稿（json / txt / md，同名；json 优先）
- [ ] 2. 跑 cli.py qa（检查阶段进桶 A/P；默认再跑复审：参考 TTS vs 原 mp3 逐字拼音。`--no-review` 可关）
- [ ] 3. 按脚本输出回复；逻辑对照近邻锚点，只评列出的例子，不改分数
- [ ] 4. 把报告中每条桶 A 错误写入 fail 库（source=script，必填 script_reason 与 agent_reason）。桶 P 不自动写。
- [ ] 5. 对 6 个典型例逐条问用户合格/不合格；用户说先不标则跳过
- [ ] 6. 标完后跑 cli.py calibrate。未达 20 条标注或 8 条人机不一致只报计数。达到则贴建议，问用户是否改；未确认不要改 score.py / scoring.md，也不要改 CER / 停顿毫秒
- [ ] 7. 未要求时不要列出其余句子
```

在 `zh-speech` 目录：

```bash
python cli.py qa .
```

英文加 `--lang en`。强制重识别加 `--force-asr`。JSON 加 `--json`。不读记忆库加 `--no-memory`。对照课件发音修正加 `--courseware courseware.json`。默认复审可用 `--no-review` 关掉。

校准：

```bash
python cli.py calibrate
```

正确稿优先级：同名 `.json` > `.txt` > `.md`。

### 分桶（一条句子只进最高优先级）

1. **A 发音错误**：CER≥8%，或缺拉丁字母/课件关键词，或标点连读（句读标点未停顿且 ASR 粘字），或 gate=fail。全部列出，不占 6 例。
2. **P 多音字 / 读音**：高证据读音不符，或课件 `pronunciations` 与语境应读不一致。全部列出，不占 6 例，不扣整课错误惩罚，不自动入库。规则见 [rules/polyphone.md](rules/polyphone.md)。
3. **B 不流畅**：停顿/拖音/吞音/语速出带。典型例最多 4 条。
4. **C 综合分 < 76**。

6 例只从非 A、非 P 中挑：先 B（最多 4）→ 再 C → 再从合格句抽低/中/高。

**字母边界停顿**：前文以拉丁字母或数字结束（含一、二、三、四、五等），中间是逗号或句号（顿号同样），后文以拉丁字母开头，就在标点后加 `<#0.1#>`。错误如 `CD，AC`、`四、CP`；正确如 `CD，<#0.1#>AB`、`四、<#0.1#>CP`。

综合判定（错误/不合格/待审/合格）是检查+复审的合成标签，**不改**综合分。`shuai4` vs `lv4` 靠复审逐字拼音，见 [rules/review.md](rules/review.md)。

### 回复与标注

直接采用脚本打印的 Markdown。可补一句「逻辑」（不计分），只针对列出的错误、多音字、综合判定和典型例。桶 P 先看是不是音高误报；不要把 P 改成 A，也不要改综合分。给用户看时**不要写 mp3 文件名或 clip hash**：优先写课件节点，对不上就写原稿文本。

合格近邻 = 可放行；不合格近邻 + 原因 = 要打回。两库皆空或没有近邻时跳过对照。

桶 A 错误句立刻写入 fail 库，不要问合不合格。桶 P 不要自动入库。错误和 6 个典型例都写修改建议，发不发由用户决定。

```bash
python cli.py memory append fail --json-file record.json
python cli.py memory append pass --json-file record.json
```

详见 [rules/memory.md](rules/memory.md)。

## 规则

- 分桶与口误：[rules/disfluency.md](rules/disfluency.md)
- 多音字（桶 P）：[rules/polyphone.md](rules/polyphone.md)
- 打分：[rules/scoring.md](rules/scoring.md)
- 复审对照：[rules/review.md](rules/review.md)
- 标注入库：[rules/memory.md](rules/memory.md)
- 多音字知识库：[rules/polyphones.json](rules/polyphones.json)，课件组词补丁：[rules/polyphone_extra.json](rules/polyphone_extra.json)
