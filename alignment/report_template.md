# S01E01 Wiki + 原音频强制对齐

当前 {total} 条 utterance：**{accepted} 条自动候选、{null_count} 条 null**。保留 Wiki 原文、角色、原 ID 与发言边界。自动候选不等于逐句人工通过；用户已确认词尾截断问题解决。

## 流程

1. Wiki 文本仅做小写与标点规范化，按顺序拼成一个 manifest 项，保留 utterance 分隔符。
2. 官方 NeMo 2.5.3 / Citrinet-256 对整集原始音频做 CTC Viterbi 对齐，`align_using_pred_text=false`。
3. 词时长明显异常或缺少有效边界时，整条保持 null。
4. 本地 wav2vec2-base 权重对 NeMo 候选窗口做字符级强制对齐，复核词尾，不运行额外转写。
5. 末词字符平均分至少 .45、末字符分至少 .1、两模型尾界差在 -0.2 至 +0.8 秒内才保留候选。该门限是启发式，不是准确率。
6. 试听独立增加最多 120 ms 尾部余量，截于下一条发言之前；余量不属于正式对齐边界。

没有使用旧 ASR 文本或时间，没有运行 SenseVoice、pyannote 或 Whisper 转写。MFA 本轮未运行。Wiki 明写的 Haha/Ho-Ho 保留原文与证据，语词播放从后续单词开始。

整词 CTC token 的 80 ms 峰值不能代表完整发音长度。两个截尾样本的复核结果：

| source_record | 末词 | NeMo 原结束 | 复核结束 | 实际试听结束 |
|---|---|---:|---:|---:|
{examples}

## 实测耗时

| 阶段 | 秒 |
|---|---:|
| NeMo 声学推理与目标准备 | {acoustic_seconds:.2f} |
| NeMo Viterbi | {viterbi_seconds:.2f} |
| NeMo 总运行（含模型加载，不含下载） | {run_seconds:.2f} |
| 字符级复核（含权重加载） | {tail_seconds:.2f} |

## 保留 null 的发言

| source_record | Wiki 台词 | 原因 |
|---|---|---|
{rejected}

## 运行和文件

项目根目录运行 `python run_alignment.py` 完成全部阶段；`python run_alignment.py --stage report` 仅更新报告与试听页。详细说明见项目 README。

- `utterances.json`：原文、nullable 时间、原始候选、词尾检查及独立 playback 范围。
- `nfa/ctm`：原生 CTM，不写入播放余量。
- `word_tail_character_check.json`：字符级声学复核证据。
- `acoustic_evidence.pt` / `viterbi_path.pt`：本机生成的模型证据。
- `inputs.json` / `run.json` / `stages.json`：来源校验、命令与耗时。
- `review.html`：正式候选、前后文、原始候选的本地试听。

参考：[NVIDIA NFA 文档](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tools/nemo_forced_aligner.html)、[TorchAudio CTC 边界说明](https://docs.pytorch.org/audio/master/tutorials/ctc_forced_alignment_api_tutorial.html)。
