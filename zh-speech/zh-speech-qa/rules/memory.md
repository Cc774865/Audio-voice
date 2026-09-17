# 标注入库

两库共用：桶 A 错误句由脚本/Agent 写入不合格库；6 个典型例仍由用户逐条判定。

## 库

| 库 | 文件 | 何时写 |
|---|---|---|
| 合格 | [memory/pass.jsonl](../memory/pass.jsonl) | 用户把典型例标成合格 |
| 不合格 | [memory/fail.jsonl](../memory/fail.jsonl) | 桶 A 错误句（`source=script`）；用户把典型例标成不合格（`source=human`） |

只追加，不覆盖。同一 `id + course + source` 默认跳过，避免整课重跑重复入库。

## 错误句（报告发出后立刻写，不要问用户）

报告里的每一条桶 A 都必须进 `fail.jsonl`，`source` 为 `script`。不要等人选合格/不合格。

必填：

- `script_reason`：脚本打印的原因（CER、缺词、gate=fail）
- `agent_reason`：你为什么认为它错（对照原稿 vs ASR 用一句话说清，例如「课件词 CAE 被听成 CE」）

错误句仍全部列出、不占 6 例。

## 典型例（错误句写完后再问）

一次只问一条。用户说「先不标 / 跳过」则停。

1. 贴出第 *i* 条：`id`、分数、脚本理由、原稿。
2. 问用户：选项仅 **合格** / **不合格**（普通对话即可）。
3. 选不合格：再问一句「为什么不合格？」，拿到非空原因再入库（`source=human`，必填 `human_reason`）。
4. 调用 `memory.py append`，再问下一条。
5. 6 条结束（或不足 6 条时标完现有的）后跑 `memory.py list`，用计数收尾，不要把库全文打出来。

## 入库命令

在项目根目录。先把这一条写成 UTF-8 JSON 文件（含中文原因时必须走文件，不要把 JSON 塞进 PowerShell 参数），再：

```bash
python cli.py memory append fail --json-file record.json
python cli.py memory append pass --json-file record.json
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

典型例不合格另加 `human_reason`，`source` 用 `human`（可省略，有 `human_reason` 即视为人工）。合格记录不要写 `human_reason`。有则带上 `pause_events`，方便下次按停顿找近邻。

## 下次质检前读库（P1）

`qa_course.py` 默认在打完分、抽出 6 例之后读两库。对每条典型例按 **分数 / CER / 停顿次数** 找最近邻，合格、不合格各挂最多 2 条。同一 `id + course` 会排除，避免把自己当成对照。

- 近邻只出现在报告里，**不改**综合分、单句分、分桶
- Agent 写「逻辑」时引用这些锚点
- `--no-memory` 可关掉

查近邻：

```bash
python cli.py memory nearest --score 73 --cer-pct 0 --pause-events 1 --k 2
```

## 阈值校准（P2）

「深度学习」在这里是少量标注上的检索 + 校准，**不重训 FunASR**。

标完后跑：

```bash
python cli.py calibrate
```

只统计人标的合格/不合格。满 **20 条标注**或 **8 条人机不一致** 才出建议；否则只报计数。

可建议的旋钮（每次最多 3 个、各挪一档）：

| 旋钮 | 现在 | 文件 |
|---|---|---|
| `LOW_SCORE` | 76 | `qa_course.py` |
| `CER_ERROR` | 8% | `cer.py` |
| 句中停顿 / 逗号最短 / 拖音毫秒 | 350 / 120 / 550 | `analyze_timing.py` |
| `BASE` / `COMPRESS` | 60 / 0.70 | `score.py` / `scoring.md` |

脚本说合格你说不合格 → 门槛偏松；反过来 → 偏严。校准脚本**只打印 diff，不写文件**。Agent 必须等你确认后才改 `score.py` / `scoring.md`（动 CER 或停顿毫秒时才改对应脚本和 `disfluency.md`）。
