---
name: zh-speech-qa
description: >-
  Courseware Chinese/English speech QA with local FunASR. Scores a folder of
  mp3 paired with json, txt, or md scripts. Use when the user asks to
  质检语音, 整课评分, 打分流畅度, 口播是否流畅, 发音错误, 标注入库, 对照原稿,
  校准阈值, or 微调门槛. Do not use for 转写, 语音转文字, 只要mp3, or 生成文稿.
---

# 中文口播质检（通用版）

对照原稿打分。默认只出**一个综合分 + 错误列表 + 6 个典型例**。近邻锚点只给「逻辑」用，不改脚本硬分。不重训 FunASR。

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
- [ ] 2. 跑 cli.py qa
- [ ] 3. 按脚本输出回复；逻辑对照近邻锚点，只评列出的例子，不改分数
- [ ] 4. 把报告中每条错误写入 fail 库（source=script，必填 script_reason 与 agent_reason）
- [ ] 5. 对 6 个典型例逐条问用户合格/不合格；用户说先不标则跳过
- [ ] 6. 标完后跑 cli.py calibrate。未达 20 条标注或 8 条人机不一致只报计数。达到则贴建议，问用户是否改；未确认不要改 score.py / scoring.md
- [ ] 7. 未要求时不要列出其余句子
```

在 `zh-speech` 目录：

```bash
python cli.py qa .
```

英文加 `--lang en`。强制重识别加 `--force-asr`。JSON 加 `--json`。不读记忆库加 `--no-memory`。

校准：

```bash
python cli.py calibrate
```

正确稿优先级：同名 `.json` > `.txt` > `.md`。

### 分桶

1. **A 发音错误**：CER≥8%，或缺拉丁字母/课件关键词，或多音字读音不对，或 gate=fail。全部列出，不占 6 例。
2. **B 不流畅**：停顿/拖音/吞音/语速出带。典型例最多 4 条。
3. **C 综合分 < 76**。

### 回复与标注

直接采用脚本打印的 Markdown。可补一句「逻辑」（不计分）。

合格近邻 = 可放行；不合格近邻 + 原因 = 要打回。

桶 A 错误句立刻写入 fail 库，不要问合不合格。典型例一次只问一条，选项仅 **合格** / **不合格**（普通对话即可，不要求特定 UI）。不合格再问原因。写入：

```bash
python cli.py memory append fail --json-file record.json
python cli.py memory append pass --json-file record.json
```

详见 [rules/memory.md](rules/memory.md)。

## 规则

- 分桶与口误：[rules/disfluency.md](rules/disfluency.md)
- 打分：[rules/scoring.md](rules/scoring.md)
- 标注入库：[rules/memory.md](rules/memory.md)
- 多音字知识库：[rules/polyphones.json](rules/polyphones.json)
