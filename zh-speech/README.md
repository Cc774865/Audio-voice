# zh-speech（通用版）

不依赖 Cursor。两条线互不调用，一次只跑一条。

| 你要做的事 | 命令 |
|---|---|
| 转写、语音转文字、只要 mp3 | `python cli.py stt <目录或mp3>` |
| 质检、打分、对照原稿、标注入库 | `python cli.py qa <目录>` |

本目录可整夹拷到别的项目。需要 **Python 3.11** 虚拟环境、ffmpeg，以及 FunASR 模型。

## 安装

在本目录或上级仓库建 `.venv`（已有仓库根目录的 `.venv` 可直接用）：

```bash
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -U "funasr==1.4.1" modelscope soundfile pypinyin
.\.venv\Scripts\python.exe cli.py warmup
```

转写缓存 `*.stt.json`，质检缓存 `*.asr.json`，不要混用。

## 命令

在本目录，或从仓库根目录写成 `zh-speech/cli.py`：

```bash
.\.venv\Scripts\python.exe cli.py stt .
.\.venv\Scripts\python.exe cli.py qa .
.\.venv\Scripts\python.exe cli.py qa . --lang en --force-asr --json
.\.venv\Scripts\python.exe cli.py calibrate
.\.venv\Scripts\python.exe cli.py memory list
```

质检要求同名 `mp3` + 正确稿（`json` > `txt` > `md`）。没有正确稿的 mp3 会跳过，不会自动改去转写。

## 给任意 Agent 用

把本文件夹放到 AI 工具能读到的位置，并让它加载：

- `zh-speech-stt/SKILL.md` — 转写
- `zh-speech-qa/SKILL.md` — 质检

说明里没有 Cursor 专用步骤。标注用对话问答 + `cli.py memory append`。

Cursor 原版技能仍在仓库 `.cursor/skills/`，本目录是独立拷贝。

## 校准

```bash
.\.venv\Scripts\python.exe cli.py calibrate
```

满 20 条标注或 8 条人机不一致才出建议。脚本只打印，确认后才改 `zh-speech-qa/scripts/score.py` 和 `zh-speech-qa/rules/scoring.md`。
