# Audio-voice

中文课件口播质检 Skill（2b）：本地 FunASR（中英）对照原稿挑出发音错误，再按不流畅、低分抽样。默认只输出**一个课件综合分 + 错误列表 + 6 个典型例**。错误句不计入这 6 例。

## 安装

仓库根目录就是 Cursor 项目。克隆后 Skill 位于 `.cursor/skills/zh-speech-qa/`。

本机需要 **Python 3.11** 虚拟环境（不要用 3.14）和 ffmpeg：

```bash
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -U "funasr==1.4.1" modelscope soundfile
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/asr_local.py --warmup
```

`--warmup` 只下载中文 `paraformer-zh` 和英文 `paraformer-en`，不装多语种模型。

触发词：质检语音、整课评分、打分流畅度、发音错误。

## 用法

每句一对同名文件：`foo.mp3` + `foo.json`（`duration` + `words[].word/begin/end`，时间为毫秒）。

```bash
.\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/qa_course.py .
```

英文口播加 `--lang en`。识别结果缓存在 `*.asr.json`，强制重跑加 `--force-asr`。

## 分桶

1. **A 发音错误**（FunASR CER≥8%、缺拉丁字母/课件词、或残句）— 全部列出，不占 6 例
2. **B 不流畅** — 典型例最多 4 条
3. **C 综合分 < 76** — 再补典型例

## 校准

单句中位数应落在 76–84。偏离时只改 `.cursor/skills/zh-speech-qa/scripts/score.py` 里的 `BASE` 和 `COMPRESS`。
