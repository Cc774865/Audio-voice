# 复审（对照参考 TTS）

检查阶段仍是原稿 vs FunASR / 发音修正。复审在此之外：用**另一套 TTS**按整句语境生成参考 mp3，再和原音频比差异。两路合成为综合判定。参考音频只写在本地旁路目录，**不** PUT 课件、不跑工作室 `tts-batch`。

## 参考音频（读音受控）

- 引擎：`edge-tts`，默认音色 `zh-CN-XiaoxiaoNeural`（`--tts-voice` 可改）
- 输入：正确稿全文（去掉 `<#x#>` / 省略号），**不带**课件 `pronunciations` 覆盖
- **读音保证**：edge-tts 拒绝 SSML `<phoneme>`（已实测），所以对语境确定的字，用**同音同调、默认读音明确**的常见字替换后再合成（「行长」的「行 háng」→「杭」，「斜率」的「率 lǜ」→「律」）。替换是逐字、可逆的，旁路 sidecar 记录 `subs`，比对前用 `restore_text` 还原原字
- 只强制“默认读音 ≠ 语境应读”的多音字，或「的/地/得」。没有合适同音字（如轻声 `de5`）时进 `unforced`，交给 edge-tts 语境
- 目录：`<口播目录>/.ref-tts/`，按文本+音色+替换缓存
- 逐字拼音模板：`<口播目录>/.ref-tts/.pinyin-tpl/`

## 复审比什么

1. 原音频 ASR vs 参考 TTS ASR 的 CER（参考先还原同音替换）
2. 参考 TTS ASR vs 原稿 CER（参考是否贴稿；≥8% 则参考本身不可信，不当金标）
3. **逐字拼音**：原稿里每个汉字，分别从原音频、参考 TTS 裁出该字，估出拼音，再看两边是否相同
   - **被强制的字**：参考读音**已知**（就是强制值），不再“识别参考”，只用原音频识别去比应读，消除参考侧噪声
   - 声母韵母（base）：多音字（组词命中/多读）用模板比 MFCC，`base_confident` 才下结论；否则该字记 unresolved
   - 声调：用参考/模板的**归一化 F0 轮廓**做相关，取候选里最像的调；F0 相关和 margin 达标才 `tone_confident`
   - 结构助词「的/地/得」读 de 时不比调
   - FunASR 仍然不出拼音；`shuai4` vs `lv4` 这种同调异读，靠 base 对比

综合判定用 `pinyin_disagree`（原音频拼音 ≠ 参考）。识别证据不足的字进 `pinyin_unresolved`，默认不阻断（桶 P 仍不合格，其余放行）；`--strict` 才留待审。

## 识别可信度

- `rules/pinyin_confidence.json`：`min_cosine`/`base_margin`/`tone_conf`/`tone_f0_min`/`tone_margin`
- 由 `scripts/pinyin_selftest.py` 用已知读音的 TTS 语料实测得出（基线：base 置信准确率 ~93%、tone ~85%）。**不要**手改，先跑：
  ```bash
  .\.venv\Scripts\python.exe .cursor/skills/zh-speech-qa/scripts/pinyin_selftest.py
  ```
  `--limit 100 --write` 才会写回阈值。

## 综合判定（全自动，分来源收敛）

默认**不留待审**，按来源给结论：

| 判定 | 何时 |
|---|---|
| **错误** | 桶 A 且复审也拉开；或检查阶段确定性问题（连读/gate/漏词/发音修正）+ 复审拼音指向读错 |
| **不合格** | 检查阶段确定性桶 A（连读/gate/漏词/发音修正）；或桶 P/B/C；或复审拼音确认读错；或原/参 CER≥8% 且参考贴稿 |
| **合格** | 桶 A 但只是字面同音（拼音 CER 低）或参考不可信 → 疑似 ASR 误报；其余无异常见 |
| **待审** | 仅 `--strict` 保留：证据不足且无法按来源归类的 |

- **拼音级 CER**：发音检查用声母韵母（忽略声调）比，ASR 同音字（作/做、图象/图像、由/有、到/倒）不再误报为桶 A；真正改读（shuài/lǜ）仍会露出
- **桶 A 分原因**：`bucket_a_kind` = liaison / gate / keyword / pronunciation / cer。前四类是确定性检查，直接给结论；只有 `cer` 才交复审按“ASR 误报 vs 真读错”分流
- 复审拼音 `pinyin_unresolved`（证据不足）不再阻断：桶 P 仍不合格（检查阶段已存疑），其余按合格放行
- `--strict` 恢复旧的待审行为，供人工复核
- 综合判定**不改**课件综合分和桶 A 惩罚。`--no-review` 跳过复审，判定只按检查阶段映射（A→错误，P/B/C→不合格，ok→合格）。

