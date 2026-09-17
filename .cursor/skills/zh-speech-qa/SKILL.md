---
name: zh-speech-qa
description: >-
  Courseware Chinese/English speech QA with local FunASR. Scores a folder of
  mp3+json sentence pairs, puts pronunciation errors in bucket A, then reports
  one course score plus error clips and six typical examples. After the report,
  write bucket-A errors into the fail memory store with why they failed, then
  label each of the six typical examples pass/fail. Use when the user asks to
  质检语音, 整课评分, 打分流畅度, 口播是否流畅, 发音错误, 标注入库, or to review a set of clips.
---

# 中文口播质检（2b）

本地 FunASR（中英）对照原稿，挑出发音错误；再按不流畅、低分抽样。默认只出**一个综合分 + 错误列表 + 6 个典型例**，不要把全部句子打出来。报告发出后：先把错误句写入不合格库（带判定原因），再对 6 例逐条标合格/不合格。

必须用项目 `.venv`（Python 3.11），不要用系统 Python 3.14。

## 流程

```
- [ ] 1. 确认目录里是成对的 mp3 + json
- [ ] 2. 跑 qa_course.py（FunASR 进桶 A）
- [ ] 3. 按脚本输出回复；逻辑只评这几条例子的口播稿
- [ ] 4. 把报告中每条错误写入 fail 库（source=script，必填 script_reason 与 agent_reason）
- [ ] 5. 对 6 个典型例逐条标注入库（见 rules/memory.md）；用户说先不标则跳过
- [ ] 6. 未要求时不要列出其余句子
```

### 打分命令

在项目根目录：

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/qa_course.py .
```

英文口播加 `--lang en`。强制重识别加 `--force-asr`。JSON 调试加 `--json`。

单句仍可用 `qa_one.py`（无 FunASR）。

### 分桶（一条句子只进最高优先级）

1. **A 发音错误**：CER≥8%，或缺拉丁字母/课件关键词，或 gate=fail。**全部列出，不占 6 例。**
2. **B 不流畅**：停顿/拖音/吞音/语速出带。最多取 4 条进典型例。
3. **C 综合分低**：单句分 < 76。

6 例只从非 A 中挑：先 B（最多 4）→ 再 C → 再从合格句抽低/中/高。没有错误时这 6 条就是给人审的样本。

### 回复模板

直接采用脚本打印的 Markdown。可补一句「逻辑」判断（不计分），只针对列出的错误和典型例。

报告发出后立刻把**错误句写入 fail 库**，再进入典型例标注入库。错误句不要问用户合不合格；每条必须带脚本原因（`script_reason`）和你认为它错的原因（`agent_reason`）。典型例一次只问一条：AskQuestion 选项为 **合格** / **不合格**；不合格再追问一句原因。写入命令见 [rules/memory.md](rules/memory.md)。

## 规则

- 分桶与口误：[rules/disfluency.md](rules/disfluency.md)
- 单句与整课打分：[rules/scoring.md](rules/scoring.md)
- 标注入库：[rules/memory.md](rules/memory.md)
