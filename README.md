# Peppa Wiki 台词强制对齐

## 仓库范围

本仓库仅保存项目源码、测试代码、固定运行配置和说明文档。**不包含视频、音频、模型权重、虚拟环境、Wiki 采集正文或生成结果。** 输入视频和 Wiki JSON 需要在本机准备；`output/`、`inspection/`、`wiki-input/` 等本地数据目录均不上传。

`configs/whisperx_b12.fixed.json` 是原运行机器的不可变配置快照，包含本机绝对路径和权重／源码校验值；它不是跨机器开箱即用的配置。迁移环境时应另建配置并重新验证，不能悄悄改写这份已确认的记录。

当前模型定位与 Wiki 文本对应仍有已发现的错误；数据完整性检查通过不代表音频定位正确。`build_source_comparison.py` 提供模型原始输出与 Wiki 合并结果的并排核查，原始结果不修正。

## 当前：第一季固定 B12 批处理

用户已确认 B12 第一集版本并授权处理第一季。批量入口为 `run_season_b12.py`，使用同一份锁定配置，支持按集号匹配、分阶段复用模型、单集失败隔离和断点续跑。完整运行方法见 [BATCH_SEASON1.md](BATCH_SEASON1.md)。

输出总入口为 `output/whisperx_b12/season1.html`，逐集状态与耗时为 `season1_summary.json`；已完成的第一集校验后复用。后文关于“等待第一集确认”的记录属于此前验证阶段，已由本次用户授权更新。

## 当前固定方案：B12 整集 S01E01

固定配置为 `configs/whisperx_b12.fixed.json`，校验文件为同目录 `.sha256`。配置从已成功的局部 B 实验脚本和记录提取，完整记录解码默认值、VAD、对齐、说话人分离、软件版本及模型／源码校验值；运行时校验后加载，不允许临时覆盖参数。

注意配置同时保留 `load_model.vad_options.chunk_size=30`（原 B 组加载时的继承默认值）与 **`transcribe.chunk_size=12`（Pyannote 实际合并窗口）**；后者控制本方案的分块，不能把两个字段混为一谈或自行改写。

本次完整结果：`output/whisperx_b12/S01E01/review.html`；43 条 Wiki 发言全部保留，角色与原文以 `output/wiki/season1/episodes/S01E01.json` 为准。`utterances.json` 保留异常候选和原因，缺失候选也提供相邻原音试听，不插值补造时间。`REPORT.md` 记录整集耗时与重点检查，所有原始中间数据同目录保留。

`run_fixed_b12.py` 只读取固定配置运行；为防覆盖，目标目录已有运行记录时会停止。首次固化已完成，**不要再次执行 `--freeze-from-b`**。只刷新发言列表和试听页：

```powershell
python -m alignment.b12_report
```

当前整集模型流程 24.260 秒，第86／87条与用户认可的局部B切点相差不超过12 ms；仍有待试听异常，未将整集标为验证成功。其他集数尚未启动，需先完成这一集试听验证。

## S01E01 独立 WhisperX 原始逐词试听

`output/whisperx_s01e01_native/review.html` 是新一轮只输入原视频的 WhisperX 结果：65 个原始句段、323 个词，每个词可点击试听原始切点，默认余量为 0。未读取 Wiki 或 NeMo，不做文本匹配或导出后的时间修正。页面内嵌音频，可直接用浏览器打开。

运行 `./.whisperx-cuda/Scripts/python.exe run_whisperx_native.py` 会重新执行 ASR、原生对齐、说话人分离并生成逐词页。`asr.raw.json`、`aligned.raw.json`、`diarization.raw.json` 与最终 `S101 Muddy Puddles.json` 分别保留各阶段原始输出。只重建页面可调用 `alignment.native_word_review.build`。

这轮原始对齐结果与上一轮完全相同，用户指出的末尾台词仍输出在 256.698–259.759 秒；保留该失败结果供试听和方案评估。

## S01E01 WhisperX 指定参数对比（2026-11-17）

本轮对比页为 `output/whisperx_s01e01_v2/review.html`，双击即可打开，音频已内嵌，原始切点播放无需本地服务器。全部 43 句并排展示，包括 NeMo 17 句 null 的原始候选。

使用官方 WhisperX 接口运行 large-v3、CUDA float16、batch 4、beam 5、temperature 0、pyannote VAD（0.50 / 0.363）、community-1 说话人分离、interpolate=ignore。完整运行参数、软件版本和耗时见该目录 `run.json`；原始输出为 `S101 Muddy Puddles.json`。

Wiki 使用 `output/wiki/season1/episodes/S01E01.json`。对照只做文本关联，保留 WhisperX 原始识别文本和词时间，未拿 Wiki 再做声学强制对齐。逐词错漏、额外识别词及全部 NeMo 状态见 `comparison.json`。这些自动提示不是准确率，当前没有逐句人工听验结论。此前 `output/comparison/S01E01` 为运行方式不符的旧实验，不用于本轮评价。

复跑与重新生成网页：

```powershell
./.whisperx-cuda/Scripts/python.exe run_whisperx_v2.py
python -m alignment.whisperx_v2_report
```

`.whisperx-cuda` 是项目独立 CUDA 环境；本轮复用完整的本地模型缓存，没有要求重新登录。NeMo 原有环境和结果不变。

## NeMo 原流程

当前保留 **Wiki 文本 + 原始音频 → NeMo Forced Aligner → 字符级词尾复核 → 逐句试听**。范围仍为 S01E01，未开始批量音频处理。

## 使用

在项目根目录运行：

```powershell
# 完整流程：会重新运行本集对齐和词尾复核
python run_alignment.py

# 只重新生成报告与试听页，不运行模型
python run_alignment.py --stage report

# 仅重做字符级词尾复核并应用结果
python run_alignment.py --stage tails
python run_alignment.py --stage report

# 可选本地试听服务，支持音频 Range 请求
python serve_preview.py
```

服务启动后打开 [S01E01 试听页](http://127.0.0.1:8766/review.html)。也可直接用浏览器打开 `output/forced_alignment/S01E01/review.html`。

统一入口自动使用项目的 `.nemo-venv/Scripts/python.exe`。现有环境和模型已保留。`--stage nfa` 只生成 NeMo 原始结果，`--stage export` 只导出 NeMo 候选；通常使用完整流程即可。

## 必要输入

- `output/wiki/episodes/S01E01.json`：本轮验证使用的 Wiki 导出，按原顺序提取 43 条 utterance。
- `output/forced_alignment/S01E01/source_audio.wav`：原始 MP4 提取的单声道 16 kHz PCM 音频。
- `output/forced_alignment/S01E01/citrinet.nemo`：本地 NVIDIA Citrinet-256 权重。
- PyTorch 缓存中的 `wav2vec2_fairseq_base_ls960_asr_ls960.pth`：字符级对齐权重，使用 `torch.hub.get_dir()` 定位。

需要重新提取原音频时：

```powershell
ffmpeg -i "F:/小孩动画片/英文/peppa/第1季52集/S101 Muddy Puddles.mp4" -ac 1 -ar 16000 -c:a pcm_s16le output/forced_alignment/S01E01/source_audio.wav
```

不从旧 ASR 复制时间，不用旧 ASR 决定台词，不运行 SenseVoice、pyannote 或重复转写。

## 目录

```text
run_alignment.py              统一运行入口
alignment/
  prepare.py                  Wiki manifest 与 NeMo 运行
  nemo_bootstrap.py            非发音分隔符适配、声学证据与计时
  export.py                    原生候选导出与异常长词拒绝
  ctc.py                      字符级 CTC Viterbi
  word_tails.py               词尾字符级声学复核
  tail_checks.py              证据门限、null 与独立试听余量
  report.py                   结果验证、报告与试听页
  report_template.md          当前报告模板
  vendor/nemo_forced_aligner/ NVIDIA NeMo 2.5.3 官方源码
wiki_transcript.py            Wiki 正文清洗
build_wiki_season1.py         已采集第一季 Wiki 的离线归档
serve_preview.py             本地试听服务
tests/                       当前流程及 Wiki 清洗的回归测试
```

## 结果约定

`utterances.json` 保留原 Wiki ID、文本、角色和 utterance 边界。`nfa_candidate` 与 `words` 是原始模型证据；正式 `start` / `end` 在证据不足时为 `null`。`playback` 单独记录最多 120 ms 的尾部试听余量，不能把它当成模型边界。

这轮结果为 26 条自动候选、17 条 null；用户指出的 `first`、`doing` 截尾已通过字符复核修正并确认解决。完整证据和耗时见 `output/forced_alignment/S01E01/REPORT.md`。其他自动候选仍需试听核查。

旧 ASR、说话人分离、话轮分组及临时探针脚本已删除；已有音频、JSON、截图和历史结果保留，以便追溯。当前流程不依赖它们。

## 环境与检查

当前 Windows CPU 环境为 `.nemo-venv`。主要版本见 `requirements.txt`，本轮完整版本记录见输出目录的 `environment_versions.json`。NeMo 的额外导入依赖较多；保留现有环境即可运行，不应在全局环境安装或升级这些依赖。

```powershell
./.nemo-venv/Scripts/python.exe -m unittest discover -s tests -v
```

Wiki 采集和清洗说明见 [WIKI_TRANSCRIPTS.md](WIKI_TRANSCRIPTS.md)。
