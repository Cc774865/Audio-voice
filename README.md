# Audio-voice

中文课件口播质检 Skill（一期）：用字级时间戳 JSON 打流畅度分，再由 Agent 判断口播稿是否合逻辑。

当前**没有 ASR**。错字错读、发音、自然度会在报告里标明未测。

## 安装

仓库根目录就是 Cursor 项目。克隆后 Skill 位于：

`.cursor/skills/zh-speech-qa/`

Cursor 会自动加载。触发词：质检语音、打分流畅度、口播是否流畅、语音有没有读错。

## 用法

同目录下要有 `foo.mp3` 对应的 `foo.json`（`duration` + `words[].word/begin/end`，时间为毫秒）。

```bash
python .cursor/skills/zh-speech-qa/scripts/qa_one.py 3b88ea44a3aa976f.json
python .cursor/skills/zh-speech-qa/scripts/qa_one.py --batch .
```

分数 0–100，这批课件数据校准后中位数约 80。残句等门槛失败会 `gate=fail` 且分数封顶 60。

## 校准

中位数应落在 76–84。偏离时只改 `.cursor/skills/zh-speech-qa/scripts/score.py` 里的 `BASE` 和 `COMPRESS`。
