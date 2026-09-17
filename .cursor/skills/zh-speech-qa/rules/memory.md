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
2. 用 AskQuestion，选项仅 **合格** / **不合格**。
3. 选不合格：再问一句「为什么不合格？」，拿到非空原因再入库（`source=human`，必填 `human_reason`）。
4. 调用 `memory.py append`，再问下一条。
5. 6 条结束（或不足 6 条时标完现有的）后跑 `memory.py list`，用计数收尾，不要把库全文打出来。

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

典型例不合格另加 `human_reason`，`source` 用 `human`（可省略，有 `human_reason` 即视为人工）。合格记录不要写 `human_reason`。
