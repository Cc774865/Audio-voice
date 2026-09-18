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
  For bucket A and P, write qualitative fix suggestions (no replacement script,
  no pause markers). After labeling, run calibrate.py for knob suggestions
  (LOW_SCORE / CER / pause-ms / BASE) only when labels or disagreements are
  enough; never apply without confirmation.
  Use when the user asks to 质检语音, 整课评分, 打分流畅度, 口播是否流畅, 发音错误,
  标注入库, 对照原稿, 复审拼音, 校准阈值, 微调门槛, 修改建议, or to review scored
  clips. Do not use for 转写, 语音转文字, 只要mp3, or 生成文稿.
---

# 中文口播质检（通用版）

对照原稿打分。默认再跑复审：参考 TTS 和原音频**逐字比拼音**，合成错误/不合格/待审/合格（**不改**综合分）。默认只出**一个综合分 + 错误列表 + 多音字列表 + 综合判定 + 6 个典型例 + 桶 A/P 修改建议（事实）**，不要把全部句子打出来。报告发出后：先把桶 A 错误句写入不合格库（带判定原因），再按当条错误写出定性建议；桶 P 只在逻辑里评，建议可写，不自动入库、不扣整课错误惩罚。近邻锚点只给「逻辑」用，**不改脚本硬分**。不重训 FunASR。

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
- [ ] 2. 跑 cli.py qa（检查阶段进桶 A/P；默认再跑复审：参考 TTS vs 原 mp3 逐字拼音，出综合判定。`--no-review` 可关）
- [ ] 3. 按脚本输出回复；逻辑对照近邻锚点，只评列出的例子，不改分数
- [ ] 4. 把报告中每条桶 A 错误写入 fail 库（source=script，必填 script_reason 与 agent_reason）。桶 P 不自动写。
- [ ] 5. 对 6 个典型例逐条问用户合格/不合格；用户说先不标则跳过
- [ ] 6. 标完后跑 cli.py calibrate。未达 20 条标注或 8 条人机不一致只报计数。达到则贴建议，问用户是否改；未确认不要改 score.py / scoring.md，也不要改 CER / 停顿毫秒
- [ ] 7. 未要求时不要列出其余句子
- [ ] 8. 按报告里「修改建议」的脚本事实，为每条桶 A / 桶 P 现写一条定性建议；不要写替换稿或停顿标记
```

在 `zh-speech` 目录：

```bash
python cli.py qa .
```

英文加 `--lang en`。强制重识别加 `--force-asr`。JSON 加 `--json`。不读记忆库加 `--no-memory`。对照课件发音修正加 `--courseware courseware.json`。默认复审（`edge-tts` 按语境生成参考 mp3）；`--no-review` 关掉，`--force-tts` 强制重生成参考音频。

校准：

```bash
python cli.py calibrate
```

正确稿优先级：同名 `.json`（带字级时间戳）> `.txt` > `.md`。txt/md 只提供对照文本，停顿/拖音改用 FunASR 时间戳。

### 分桶（一条句子只进最高优先级）

1. **A 发音错误**：CER≥8%，或缺拉丁字母/课件关键词，或标点连读（句读标点未停顿且 ASR 粘字），或 gate=fail。全部列出，不占 6 例。
2. **P 多音字 / 读音**：高证据读音不符，或课件 `pronunciations` 与语境应读不一致。全部列出，不占 6 例，不扣整课错误惩罚，不自动入库。规则见 [rules/polyphone.md](rules/polyphone.md)。
3. **B 不流畅**：停顿/拖音/吞音/语速出带。典型例最多 4 条。
4. **C 综合分 < 76**。

6 例只从非 A、非 P 中挑：先 B（最多 4）→ 再 C → 再从合格句抽低/中/高。

### 复审（默认开）

检查阶段之后，用 `edge-tts` 按原稿语境生成参考 mp3（不带课件 `pronunciations`），再和原音频逐字比拼音。FunASR 只出汉字，`shuai4` vs `lv4` 这种同调异读靠这一步。报告字段是 `pinyin_disagree`，不要当成只比调值。综合判定不改课件综合分。`--no-review` 可关。细节见 [rules/review.md](rules/review.md)。

- 每个字都估原音频拼音和参考 TTS 拼音，看两边是否相同
- 多种声韵（组词命中）用模板比声母韵母；声调只在组词命中、发音修正、或本来就要听音高的字上比
- 参考音频写在 `<口播目录>/.ref-tts/`，不要写进课件

### 回复与标注

直接采用脚本打印的 Markdown。可补一句「逻辑」（不计分），只针对列出的错误、多音字、综合判定和典型例。桶 P 先看是不是音高误报；不要把 P 改成 A，也不要改综合分。综合判定（错误/不合格/待审/合格）是检查+复审的合成标签，**不改**综合分。

合格近邻 = 可放行；不合格近邻 + 原因 = 要打回。两库皆空或没有近邻时跳过对照。

桶 A 错误句立刻写入 fail 库，不要问合不合格。桶 P 不要自动入库。典型例一次只问一条，选项仅 **合格** / **不合格**（普通对话即可）。不合格再问原因。写入：

```bash
python cli.py memory append fail --json-file record.json
python cli.py memory append pass --json-file record.json
```

详见 [rules/memory.md](rules/memory.md)。

### 修改建议（桶 A / 桶 P）

脚本只出事实（`suggestions[]`，`advice` 为空）。按当条错误现写方向。

- 只写方向，不写整句替换，不写停顿标记
- 连读：指出哪两个字间隔太短，让对方适当加间隔
- 多音字 / 发音修正：指出哪个字读音不对，让对方按语境改口播读音（可带应读/听成；修正栏写错的让对方改掉错误拼音）
- 缺词 / CER / gate：指出漏词、和原稿差太多、或不完整/重复，让对方核对后重出口播

## 规则

- 分桶与口误：[rules/disfluency.md](rules/disfluency.md)
- 多音字（桶 P）：[rules/polyphone.md](rules/polyphone.md)
- 打分：[rules/scoring.md](rules/scoring.md)
- 复审对照：[rules/review.md](rules/review.md)
- 逐字拼音：[scripts/pinyin_audio.py](scripts/pinyin_audio.py)
- 参考 TTS：[scripts/ref_tts.py](scripts/ref_tts.py)
- 复审脚本：[scripts/review.py](scripts/review.py)
- 标注入库：[rules/memory.md](rules/memory.md)
- 阈值校准：[scripts/calibrate.py](scripts/calibrate.py)（只出建议，确认后才改文件）
- 多音字知识库：[rules/polyphones.json](rules/polyphones.json)，课件组词补丁：[rules/polyphone_extra.json](rules/polyphone_extra.json)
