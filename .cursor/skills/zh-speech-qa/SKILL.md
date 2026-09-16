---
name: zh-speech-qa
description: >-
  Phase-1 Chinese speech QA for courseware TTS: score fluency, speed, pauses,
  and rule-based text issues from word-timestamp JSON, then judge script logic.
  Use when the user asks to 质检语音, 打分流畅度, 口播是否流畅, 语音有没有读错,
  or to score an mp3/json clip like 3b88ea44a3aa976f.
---

# 中文口播质检（一期）

无 ASR。用字级时间戳打流畅度分，再用口播稿做逻辑判断。错读、发音、自然度标为未测。

## 何时执行

用户提到质检 / 流畅度 / 打分 / 某条 mp3 或 json 时，按下面做。

## 流程

```
- [ ] 1. 定位时间戳 JSON
- [ ] 2. 跑 qa_one.py
- [ ] 3. 读分数与 issues
- [ ] 4. 审口播稿逻辑（不计分）
- [ ] 5. 按模板回复，写明局限
```

### 1. 定位 JSON

同目录、同主文件名：`foo.mp3` → `foo.json`。没有 JSON 就停，不要编时间戳。

### 2. 打分（必须跑脚本，不要口算）

在项目根目录：

```bash
python .cursor/skills/zh-speech-qa/scripts/qa_one.py <json或mp3路径>
```

批量校准：

```bash
python .cursor/skills/zh-speech-qa/scripts/qa_one.py --batch .
```

中位数应落在 76–84。只允许改 `scripts/score.py` 里的 `BASE` 和 `COMPRESS`。

### 3. 逻辑（Agent，不计分）

读 `transcript_ref`，判断：

- 句子是否完整、设问与前后是否衔接
- 课件讲解是否自相矛盾或缺条件
- 不要根据「听感」编造 ASR 没检出的错读

结论写入报告的「逻辑」段：`ok` / `weak` / `fail` + 一句话理由。

### 4. 回复模板

```markdown
**分数**：N / 100（gate: pass|fail）
**语速**：X 字/分
**问题**：无 / 列出 issues
**逻辑**：ok|weak|fail — 理由
**局限**：无 ASR，错字错读、发音、自然度未测
```

gate=fail 时分数已被上限 60。建议改稿或重合成后再跑同一条。

## 规则

- 口误类型：[rules/disfluency.md](rules/disfluency.md)
- 扣分与校准：[rules/scoring.md](rules/scoring.md)
