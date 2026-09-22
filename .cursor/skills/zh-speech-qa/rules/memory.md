# 标注入库

两库共用：桶 A 错误句由脚本/Agent 写入不合格库；6 个典型例由 Agent 自行判定后入库。桶 P 多音字不自动入库。不要再让用户逐条选合格/不合格。

## 库

| 库 | 文件 | 何时写 |
|---|---|---|
| 合格 | [memory/pass.jsonl](../memory/pass.jsonl) | Agent 把典型例判成合格（`source=agent`） |
| 不合格 | [memory/fail.jsonl](../memory/fail.jsonl) | 桶 A 错误句（`source=script`）；Agent 把典型例判成不合格（`source=agent`） |

只追加，不覆盖。同一 `id + course + source` 默认跳过，避免整课重跑重复入库。

## 错误句（报告发出后立刻写，不要问用户）

报告里的每一条桶 A 都必须进 `fail.jsonl`，`source` 为 `script`。不要等人选合格/不合格。桶 P 不要按错误句写进去。

必填：

- `script_reason`：脚本打印的原因（CER、缺词、gate=fail）
- `agent_reason`：你为什么认为它错（对照原稿 vs ASR 用一句话说清，例如「课件词 CAE 被听成 CE」）

错误句仍全部列出、不占 6 例。

## 典型例（错误句写完后由你判定，不要问用户）

6 例仍要出现在报告里。判定后马上入库，不要 AskQuestion。用户说「先不标 / 跳过」则停。

1. 列出第 *i* 条：`id`、分数、脚本理由、原稿、你的判定。
2. 对照综合判定、近邻锚点、脚本理由自行标 **合格** / **不合格**。同类合格近邻可放行；同类不合格近邻加原因则打回。不要把桶 B 一律判不合格。
3. 不合格：必填 `agent_reason`（一句话说为什么不合格），`source=agent`。
4. 合格：`source=agent`，不要写 `human_reason`。
5. 调用 `memory.py append`。6 条一次判完再入库即可，不必等用户。
6. 全部结束后跑 `memory.py list`，用计数收尾，不要把库全文打出来。

## 入库命令

在项目根目录。先把这一条写成 UTF-8 JSON 文件（含中文原因时必须走文件，不要把 JSON 塞进 PowerShell 参数），再：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/memory.py append fail --json-file record.json
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/memory.py append pass --json-file record.json
```

`course` 用报告里的目录名。`reason` 会记成 `script_reason`。同一句已按相同 `source` 入库则跳过（输出带 `"skipped": true`）。

桶 A 最小字段：

```json
{
  "id": "clip-stem",
  "course": "folder-name",
  "score": 60,
  "bucket": "A",
  "cer_pct": 2.1,
  "transcript_ref": "原稿",
  "transcript_asr": "ASR",
  "reason": "发音 CER 2.1%；缺 CAE",
  "source": "script",
  "agent_reason": "原稿要比较三角形 GBF 和 CAE，ASR 把 CAE 听成 CE，课件关键词缺失。"
}
```

典型例不合格用 `source=agent`，必填 `agent_reason`。合格记录同样 `source=agent`，不要写 `human_reason`。有则带上 `pause_events`，方便下次按停顿找近邻。用户以后若亲自改判，再写成 `source=human` 并填 `human_reason`。

## 下次质检前读库（P1）

`qa_course.py` 默认在打完分、抽出 6 例之后读两库。对每条典型例按 **分数 / CER / 停顿次数** 找最近邻，合格、不合格各挂最多 2 条。同一 `id + course` 会排除，避免把自己当成对照。

- 近邻只出现在报告里，**不改**综合分、单句分、分桶
- Agent 写「逻辑」时引用这些锚点
- `--no-memory` 可关掉

查近邻：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/memory.py nearest --score 73 --cer-pct 0 --pause-events 1 --k 2
```

## 阈值校准（P2）

「深度学习」在这里是少量标注上的检索 + 校准，**不重训 FunASR**。

标完后跑：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/calibrate.py
```

统计典型例判定（`source=agent` 或 `source=human`），不含桶 A 自动入库。**每满 60 条**新标注才出建议；问完是否改后跑 `calibrate.py --ack` 记下本批，再等下 60 条。未满则只报计数。

可建议的旋钮（每次最多 3 个、各挪一档）：

| 旋钮 | 现在 | 文件 |
|---|---|---|
| `LOW_SCORE` | 76 | `qa_course.py` |
| `CER_ERROR` | 8% | `cer.py` |
| 句中停顿 / 逗号最短 / 拖音毫秒 | 450 / 160 / 550 | `analyze_timing.py` |
| `BASE` / `COMPRESS` | 60 / 0.70 | `score.py` / `scoring.md` |

判定和脚本不一致 → 门槛可能偏松或偏严。校准脚本**只打印 diff，不写 score 文件**。Agent 必须等你确认后才改 `score.py` / `scoring.md`（动 CER 或停顿毫秒时才改对应脚本和 `disfluency.md`）。问完后跑 `calibrate.py --ack`。
