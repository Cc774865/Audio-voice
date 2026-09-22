---
name: zh-speech-qa
description: >-
  Courseware Chinese/English speech QA with local FunASR. Scores a folder of
  mp3 paired with json, txt, or md scripts, puts pronunciation errors in bucket A
  and polyphones in bucket P, then reviews original audio against a context-aware
  TTS by comparing per-character pinyin. Reports one course score plus error
  clips, polyphone review clips, combined verdicts, and six typical examples.
  After the report, write bucket-A errors into the fail memory store with why
  they failed, then you judge each of the six typical examples pass/fail
  and write them to memory without asking the user to pick. Bucket P
  is review-only: do not auto-write fail or change the course error penalty.
  For bucket A, bucket P, and the six typical examples, write qualitative
  fix suggestions (no replacement script, no pause markers) and send them
  to the courseware Agent only after the user confirms. After labeling, run
  calibrate.py every 60 typical-example
  labels for knob suggestions (LOW_SCORE / CER / pause-ms / BASE);
  never apply without confirmation.
  Use when the user asks to 质检语音, 整课评分, 打分流畅度, 口播是否流畅, 发音错误,
  标注入库, 对照原稿, 复审拼音, 校准阈值, 微调门槛, 修改建议, 发给课件Agent,
  or to review scored clips. Do not use for 转写, 语音转文字, 只要mp3, or 生成文稿.
---

# 中文口播质检（2b）

本地 FunASR（中英）对照原稿，挑出发音错误；多音字另进桶 P 待审；再按不流畅、低分抽样。默认再跑复审：参考 TTS 和原音频**逐字比拼音**，合成错误/不合格/待审/合格（**不改**综合分）。默认只出**一个综合分 + 错误列表 + 多音字列表 + 综合判定 + 6 个典型例 + 修改建议（错误和 6 例都写）**，不要把全部句子打出来。报告发出后：先把桶 A 错误句写入不合格库（带判定原因），再按当条错误和 6 个典型例写出定性建议；桶 P 只在逻辑里评，建议可发，不自动入库、不扣整课错误惩罚。发给课件 Agent 必须用户确认。下次质检默认先读两库，把最近邻挂在 6 例旁边，只给「逻辑」当锚点，**不改脚本硬分**。6 个典型例仍要找出来并写进报告，但合不合格由你自己判定并入库，不要再问用户选。门槛微调走 `calibrate.py`：**每满 60 条**典型例标注才出建议，**你确认后**才改 `score.py` / `scoring.md`，不重训 FunASR。问完是否改之后跑 `calibrate.py --ack` 记下本批，下一批再等 60 条。

必须用项目 `.venv`（Python 3.11），不要用系统 Python 3.14。

## 分流（只走质检）

本 Skill 只做对照打分。用户说「转写 / 语音转文字 / 只要 mp3」时**不要**用本文件，去 `zh-speech-stt`。

- **不要**运行 `.cursor/skills/zh-speech-stt/scripts/stt_course.py`
- 没有 json/txt/md 的 mp3 列入跳过，不要改去转写
- 不要把转写优化稿当作正确稿
- 课件工作室走生产环境：https://jx-admin.zmexing.com/mymath （九霄后台为 https://jx-admin.zmexing.com/ ）
- 修改建议写好后必须先给你看；未确认不要发给课件 Agent，也不要 PUT courseware.json

## 流程

```
- [ ] 1. 确认目录里是成对的 mp3 + 正确稿（json / txt / md，同名；json 优先）
- [ ] 2. 跑 qa_course.py（检查阶段 FunASR 进桶 A/P；默认再跑复审：参考 TTS vs 原 mp3 逐字拼音，出综合判定。`--no-review` 可关；`--strict` 才留待审）
- [ ] 3. 按脚本输出回复；逻辑对照近邻锚点，只评这几条例子，不改综合分或单句分
- [ ] 4. 把报告中每条桶 A 错误写入 fail 库（source=script，必填 script_reason 与 agent_reason）。桶 P 不自动写。
- [ ] 5. 对 6 个典型例自行判定合格/不合格并入库（见 rules/memory.md）；报告里写上判定，不要问用户选。用户说先不标则跳过
- [ ] 6. 标完后跑 calibrate.py。距上次微调不足 60 条典型例标注：只报计数，不改门槛。每满 60 条则贴建议，AskQuestion 问是否改；无论改不改都跑 `calibrate.py --ack`。未确认不要改 score.py / scoring.md，也不要改 CER / 停顿毫秒
- [ ] 7. 未要求时不要列出其余句子
- [ ] 8. 按报告里「修改建议」的脚本事实，为每条桶 A / 桶 P 以及 6 个典型例现写一条定性建议；合格典型例写「这条可以不改」。不要写整句替换稿。发给 Agent 的停顿秒数按当条间隔选，写入具体 `<#x#>`（x 是秒）
- [ ] 9. 问用户是否发给课件 Agent。未确认不要 POST，也不要 PUT courseware.json
- [ ] 10. 确认后：`suggest.py --locate` 对节点；404 则提示先导入，停止发送
- [ ] 11. 用已填 advice 的 JSON 生成消息，再 `jx_agent.py` 发送并轮询到结束
```

### 打分命令

在项目根目录：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/qa_course.py .
```

英文口播加 `--lang en`。强制重识别加 `--force-asr`。JSON 调试加 `--json`。不读记忆库加 `--no-memory`。发给课件 Agent 时用 `--course-id` 指定**生产环境课件 ID**。对照课件发音修正加 `--courseware courseware.json`（有 token 时 `--course-id` 也会自行拉取）。默认会做复审（`edge-tts` 按语境生成参考 mp3）；`--no-review` 关掉，`--force-tts` 强制重生成参考音频。默认全自动判定、不留待审；`--strict` 才保留待审供人工。

对节点 / 发送走生产环境 [https://jx-admin.zmexing.com/mymath](https://jx-admin.zmexing.com/mymath)（可用环境变量 `JX_BASE` 覆盖）。建议先写给你看，**你确认后**才 POST 课件 Agent。

修改建议（从 `qa_course.py --json` 产物生成 / 对节点 / 打印发给 Agent 的正文）：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/suggest.py --from-json qa.json --course-id <课件ID> --locate --out suggestions.json
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/suggest.py --from-json suggestions.json --course-id <课件ID> --print-message
```

`--print-message` 要求每条已填 `advice`。用户确认后再发（token 用环境变量 `JX_TOKEN`，不要写入仓库）：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/jx_agent.py --course-id <课件ID> --message-file agent-msg.txt
```

标注入库后校准（只打印建议；每满 60 条才出旋钮。问完是否改后 `--ack`）：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/calibrate.py
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/calibrate.py --ack
```

拼音识别自检（测 base/tone 阈值，不要手改 `pinyin_confidence.json`）：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/pinyin_selftest.py --limit 100
```

正确稿优先级：同名 `.json`（带字级时间戳）> `.txt` > `.md`。txt/md 只提供对照文本，停顿/拖音改用 FunASR 时间戳，精度低于 json。

单句仍可用 `qa_one.py`（仅 json 时间戳，无 FunASR）。

### 分桶（一条句子只进最高优先级）

1. **A 发音错误**：拼音 CER≥8%（只比声母韵母；作/做、图象/图像不算），或缺拉丁字母/课件关键词，或标点连读（句读标点未停顿且 ASR 粘字），或 gate=fail。**全部列出，不占 6 例。**
2. **P 多音字 / 读音**：高证据读音不符，或课件节点 `pronunciations` 与语境应读不一致。**全部列出，不占 6 例，不扣整课错误惩罚，不自动入库。** 规则见 [rules/polyphone.md](rules/polyphone.md)。
3. **B 不流畅**：停顿/拖音/吞音/语速出带。最多取 4 条进典型例。
4. **C 综合分低**：单句分 < 76。

6 例只从非 A、非 P 中挑：先 B（最多 4）→ 再 C → 再从合格句抽低/中/高。没有错误时这 6 条就是样本。合不合格由你判定，不要让用户选。

### 复审（默认开）

检查阶段之后，用 `edge-tts` 按原稿语境生成参考 mp3（不带课件 `pronunciations`），再和原音频逐字比拼音。FunASR 只出汉字，`shuai4` vs `lv4` 这种同调异读靠这一步。报告字段是 `pinyin_disagree`，不要当成只比调值。综合判定不改课件综合分。`--no-review` 可关。细节见 [rules/review.md](rules/review.md)。

- 参考读音受控：edge-tts 不支持 SSML `<phoneme>`，语境确定的字用**同音同调常见字**替换后合成（可逆，sidecar 记 `subs`），保证参考读成应读
- 被强制的字参考读音已知，只用原音频识别去比应读；声调用归一化 F0 轮廓模板比，base 用 MFCC 比
- 证据不足的字进 `pinyin_unresolved`，**不再阻断**：桶 P 仍不合格，其余合格放行
- 阈值在 `rules/pinyin_confidence.json`，跑 `pinyin_selftest.py` 实测（base ~93%、tone ~85%），不要在没实测前改
- 参考音频写在 `<口播目录>/.ref-tts/`，不要 PUT 课件、不要跑工作室 `tts-batch`

### 全自动判定（默认，不留待审）

- 发音检查用**拼音级 CER**（只比声母韵母）：ASR 同音字（作/做、图象/图像）不再误报为桶 A；真改读（shuài/lǜ）照样抓到
- 桶 A 按 `bucket_a_kind` 分来源：连读/gate/漏词/发音修正是确定性检查，直接给结论；只有字面 CER 类才交复审判「ASR 误报 vs 真读错」
- 分来源收敛：参考/ASR 不可信 → 合格；检查阶段已有存疑（桶 P）→ 不合格。`--strict` 才保留待审供人工

### 回复模板

直接采用脚本打印的 Markdown。可补一句「逻辑」判断（不计分），只针对列出的错误、多音字、综合判定和典型例。桶 P 先对照规则看是不是音高误报；不要把 P 改成 A，也不要改综合分。综合判定（错误/不合格/待审/合格）是检查+复审的合成标签，**不改**课件综合分。给用户看时**不要写 mp3 文件名或 clip hash**：优先写课件节点，对不上就写原稿文本。入库 JSON 仍保留 id。

写「逻辑」时先看每条典型例下面的近邻：合格近邻是正向锚点（这类可放行），不合格近邻加原因是负向锚点（同类要打回）。只写评语，不要改脚本打出的综合分或单句分。两库皆空或没有近邻时跳过对照。

报告发出后立刻把**桶 A 错误句写入 fail 库**，再对 6 个典型例自行判定并入库。错误句不要问用户合不合格；每条必须带脚本原因（`script_reason`）和你认为它错的原因（`agent_reason`）。桶 P 不要自动入库。典型例仍全部列出，但**不要** AskQuestion；对照近邻和综合判定自己标合格/不合格，不合格写 `agent_reason`。写入命令见 [rules/memory.md](rules/memory.md)。

### 修改建议（错误 + 6 个典型例）

脚本只出事实（`suggestions[]`，`advice` 为空）。桶 A、桶 P、6 个典型例都要写建议。你按当条现写方向，写入 `advice` 后再问是否发给课件 Agent；发不发由用户决定，未确认不要 POST。合格典型例建议写「这条可以不改」；发给 Agent 时默认只带需要改的，用户说全发再带上。

- 只写方向，不写整句替换。给用户看时不要堆停顿标记；发给 Agent 时 advice 里必须出现具体 `<#x#>`，不能只写「适当加间隔」，也不要用破折号或空格代替
- 连读 / 该拉开的间隔：结合当前空隙选秒数，不要一律 0.4。`<#x#>` 的 x 是秒（0.3 就是 0.3 秒，1 就是 1 秒），最长 1 秒，禁止 2～3 秒。空隙 ≤80ms 用 0.1
- **字母边界停顿（重点）**：前文以拉丁字母或数字结束（数字含 1、2 以及一、二、三、四、五等），中间是逗号或句号，后文以拉丁字母开头，就在这个标点后面加 `<#0.1#>`。顿号后同样处理。不要把字母拆进词中间
  - 错误：`AB 平行 CD，AC 是截线`；`AB 垂直于 BC，E 在边 CD 上`；`把 BC 等于四、CP 等于二`
  - 正确：`AB 平行 CD，<#0.1#>AB 垂直于 BC，<#0.1#>AD 等于 CD，<#0.1#>E 为 AC 的中点`；`把 BC 等于四、<#0.1#>CP 等于二`
- 不要把「图象 / 图像」拆开加停顿；同音词漏检先当 ASR 误报，不要改原稿
- 多音字 / 发音修正：用**同音常用字**写应读，不要写 bian4 / jiao3，也不要给课件写拼音发音修正。例如「便」应读「遍」，不要读成「便宜」；「角」应读「脚」；「题中」应读「提钟」。同音字只表示读音，不要让对方改显示汉字。修正栏里的拼音要改掉，换成同音字
- 缺词 / CER / gate：指出漏词、和原稿差太多、或不完整/重复，让对方核对后重出口播
- 节点 `has_at`：补一句「不要加停顿标记，用重做 TTS 拉开或收紧间隔」
- 发给课件 Agent 的消息抬头用 **课件ID**（不是课节ID）
- 对不上节点：消息里用原稿片段，让课件 Agent 自己找；不要给用户看 mp3 文件名
- 没有 token：请用户打开 https://jx-admin.zmexing.com/mymath/token
- 课件 404：提示先导入，不要发送
- **不要**自己 PUT `courseware.json`，改口播只通过课件 Agent

## 规则

- 分桶与口误：[rules/disfluency.md](rules/disfluency.md)
- 多音字（桶 P）：[rules/polyphone.md](rules/polyphone.md)
- 单句与整课打分：[rules/scoring.md](rules/scoring.md)
- 复审对照：[rules/review.md](rules/review.md)
- 逐字拼音：[scripts/pinyin_audio.py](scripts/pinyin_audio.py)
- 同音替换：[scripts/homophones.py](scripts/homophones.py)
- 识别自检：[scripts/pinyin_selftest.py](scripts/pinyin_selftest.py)
- 参考 TTS：[scripts/ref_tts.py](scripts/ref_tts.py)
- 复审脚本：[scripts/review.py](scripts/review.py)
- 标注入库：[rules/memory.md](rules/memory.md)
- 阈值校准：[scripts/calibrate.py](scripts/calibrate.py)（只出建议，确认后才改文件）
- 修改建议：[scripts/suggest.py](scripts/suggest.py)
- 发给课件 Agent：[scripts/jx_agent.py](scripts/jx_agent.py)（确认后才发送）
- 多音字知识库：[rules/polyphones.json](rules/polyphones.json)（由 [rules/最全多音字总汇.xls](rules/最全多音字总汇.xls) 编译），课件组词补丁：[rules/polyphone_extra.json](rules/polyphone_extra.json)
