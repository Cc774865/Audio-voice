# 打分

五维加权得到 raw，再校准到 0–100。逻辑审稿不计分。

| 维度 | 权重 | 满分锚点 |
|---|---|---|
| accuracy | 30% | 92，重复 −4、残句 −8、语气词 −2；CER 每 1% −3（最多 −30）；缺关键词每词 −6；多音字（桶 P）每处 −3 |
| fluency | 25% | 90，句中停顿 −8、拖音 −4、吞音 −3 |
| speed | 15% | 当课均值 ±60 字/分合格（本批约 183–303）；每偏离 20 字/分 −3 |
| pause | 15% | 92，每处异常停顿 −3 |
| prosody | 15% | 88，弱问句 −5，吞音/拖音各 −2 |

无任何 issue 且 gate=pass：raw +4。

## 校准

```
final = clip(BASE + COMPRESS * (raw - BASE), 0, 100)
```

当前（35 条本地课件 JSON 空跑后）：

- `BASE = 60`
- `COMPRESS = 0.70`

目标：这批数据中位数在 76–84。重跑 `--batch` 后若偏离，只改这两个数。

`gate=fail` 时 `final = min(final, 60)`。

## 随样本微调（P2）

不要重训 FunASR。用记忆库里的少量标注跑 `.cursor/skills/zh-speech-qa/scripts/calibrate.py`：满 20 条标注或 8 条人机不一致才出 `LOW_SCORE` / CER / 停顿拖音毫秒 / `BASE` `COMPRESS` 建议。脚本只打印，不改本文件。你确认后才把数字写进 `score.py` 和这里。

## 整课综合分

```
base = Σ(单句分 × 时长) / Σ时长
penalty = min(20, 80 × 桶A错误句数 / 总句数)
course = clip(base - penalty, 0, 100)
```

约 1/35 句桶 A 错误时扣 ~2 分，错误变多则加重，最多扣 20。桶 P 不计入这道惩罚。标点连读进桶 A，但不走残句那种 60 分封顶。

