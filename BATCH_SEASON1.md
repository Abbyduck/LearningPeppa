# 第一季固定 B12 批处理

## 本次核对结果（2026-11-18）

第一季已全部完成：51 集新处理，S01E01 校验后复用，失败 0 集。中途发生过一次进程中断，已从断点补齐，没有重跑已完成的转写。

- 52 集、3174 条 Wiki 发言全部保留，原文、ID、角色与其他原始 Wiki 字段核对通过。
- 2999 条有候选时间；175 条无候选，仍在完整列表中保留并提供上下文。
- 921 条带复查提示（包含无候选项）；提示包括文本差异、漏词、异常词时长等，不等于 921 条已经听验失败。
- 22064 个原始词的文字与时间未被后处理修正，试听按钮时间与原始词时间一致。
- 核对文件：`output/whisperx_b12/season1_validation.json`，52 集检查错误为 0。此结论是数据完整性检查，不代表全季已逐句人工听验。
- 本次断点续跑墙钟时间 703.617 秒；51 集累计保存的活跃处理时间为 1334.814 秒（含中断前已完成阶段，不含共享模型加载、等待和报告），不要把续跑时间当作从零处理整季的总时间。

完成时的季汇总已保存在 `output/whisperx_b12/run_history/`，便于后续再次运行时追溯这次结果。

使用用户确认的 B12 版本处理第一季。固定配置为 [configs/whisperx_b12.fixed.json](configs/whisperx_b12.fixed.json)，校验值文件为 `configs/whisperx_b12.fixed.sha256`。脚本只读取这份配置，不重新固化或调整参数。

## 输入与输出

- Wiki：`E:\Coding\peppa\output\wiki\season1\episodes`
- 视频：`F:\小孩动画片\英文\peppa\第1季52集`
- 输出：`E:\Coding\peppa\output\whisperx_b12`
- 季总入口：`output/whisperx_b12/season1.html`
- 运行进度、逐集状态和耗时：`output/whisperx_b12/season1_summary.json`
- 集号及输入文件对应关系：`output/whisperx_b12/season1_manifest.json`

按 `S01E01.json` 与视频前缀 `S101` 对应集号，不依赖标题大小写、英文拼写或弯引号。启动前检查重复集号、缺视频、缺 Wiki 和空台词；本次输入为 52 集、3174 条 Wiki 发言。

## 运行

在 `E:\Coding\peppa` 的 PowerShell 中：

```powershell
# 只核对文件对应关系，不加载模型、不推理
python run_season_b12.py --dry-run

# 执行第一季；有已完成或部分完成数据时，自动校验并续跑
./.whisperx-cuda/Scripts/python.exe -u run_season_b12.py

# 可选：保留控制台日志，追加写入，不覆盖前一次日志
./.whisperx-cuda/Scripts/python.exe -u run_season_b12.py *>> output/whisperx_b12/season1.console.log
```

上面两个执行命令任选一个，不要同时启动。脚本持有操作系统文件锁，防止两个批次同时写同一输出目录。关闭进程后锁自动释放，无需手工删除锁文件。

可限定少量集数重新检查／续跑：

```powershell
./.whisperx-cuda/Scripts/python.exe -u run_season_b12.py --episodes S01E02,S01E03
```

可显式提供目录，模型配置不变：

```powershell
./.whisperx-cuda/Scripts/python.exe -u run_season_b12.py `
  --wiki-dir "E:\Coding\peppa\output\wiki\season1\episodes" `
  --video-dir "F:\小孩动画片\英文\peppa\第1季52集" `
  --output-dir "E:\Coding\peppa\output\whisperx_b12"
```

## 固定的处理方法

1. 原视频音轨解码为 16 kHz 单声道，保留 `source_audio.wav`。
2. WhisperX：large-v3、CUDA float16、batch size 4、beam size 5、temperature 0、`condition_on_previous_text=False`。
3. pyannote VAD：onset 0.50、offset 0.363，**实际合并窗口 `transcribe.chunk_size=12`**。
4. 原 wav2vec2 `WAV2VEC2_ASR_BASE_960H` 对齐，`interpolate_method=ignore`。
5. pyannote `speaker-diarization-community-1`，不预设最少／最多说话人数，`fill_nearest=False`。
6. Wiki 只做台词、角色和发言结构的主数据；用文本对应关联原始词时间，不把 Wiki 送回声学模型，不改写 Wiki 原文，不校正模型切点。

完整默认值、版本、权重与源码 SHA256 均在固定配置中。`load_model.vad_options.chunk_size=30` 是成功 B 组加载时继承的默认值；Pyannote 实际合并由 **`transcribe.chunk_size=12`** 控制，不能看到前者就自行把配置改掉。

启动时验证固定配置校验值、软件版本、模型权重和库源码。ASR 加载后还校验真正生效的选项；任何不一致都报错，不自动降级为 CPU、不改变精度或批大小、不添加其他模型。

为降低反复加载模型的开销，批次按阶段处理：先完成待处理集数的 ASR，再统一做 wav2vec2 对齐，最后做说话人分离和输出。每阶段使用同一配置，每集输入和输出独立。

## 断点续跑与失败处理

- 已完成的 S01E01 会校验配置、视频 SHA256、Wiki 原文／角色／ID 及输出文件后复用，不重复推理。
- 每集每个阶段写完即保存状态，JSON 使用临时文件再替换，降低中断造成半份文件的风险。
- 重跑同一命令会复用已完成阶段，只补缺失阶段和报告。
- 单集失败记录在该集 `run.json` 和季汇总中，其余集数继续。再次运行同一命令会重试失败阶段；不覆盖已完成的原始阶段结果。
- 已有输出对应的视频、Wiki、固定配置或已记录的原始文件校验值发生变化时，该集报错，避免把不一致数据混在一起。需要重新推理时指定一个新的输出目录。
- `completed` / `reused` 表示自动处理完整，**不表示逐句人工听验通过**。
- `running` 是上一次写入的状态快照，不是进程仍然存活的证明。如果日志和汇总文件长时间不再更新，重新执行同一命令即可续跑；若旧进程仍在运行，文件锁会阻止第二个实例写入。
- 季总入口在磁盘上随进度更新，运行中查看时可手动刷新页面。

## 每集文件

```text
output/whisperx_b12/S01E02/
  run.json                     输入、固定配置校验值、阶段状态、异常、耗时
  config.snapshot.json         本集使用的完整固定配置
  effective_asr_options.json   实际生效的 ASR / VAD / transcribe 参数
  source_audio.wav             原视频音轨
  asr.raw.json                 未修正的原始转写和 VAD 合并块
  aligned.raw.json             未修正的 wav2vec2 词级时间轴
  diarization.raw.json         未修正的说话人分离结果
  result.whisperx.json         添加说话人编号后的模型结果
  utterances.json              Wiki 全部发言、候选时间、异常原因及原词索引
  asr_extra_tokens.json        Wiki 正文未对应到的 ASR 额外词
  focus_checks.json            本集异常和需试听位置
  focus_record_*.wav           原候选切点的零余量音频
  verification.json           数据完整性检查摘要
  review.html                 完整 Wiki 发言、逐词／逐句试听，音频内嵌
  source_compare.html         合并前 WhisperX 与合并 Wiki 后并排试听，可定位原始词来源
  source_compare.verification.json 原始文件校验值，确认对照页未修改数据
  REPORT.md                   本集处理报告与耗时
```

保留全部 Wiki 发言。无法可靠对应时正式 `start/end` 为 `null`，但 `candidate`、异常原因、原始词与上下文仍保留。完全没有识别候选时不补造时间，提供相邻原音试听。Wiki 角色与 pyannote 编号分别显示，不用说话人编号覆盖 Wiki 角色。

只重新生成某集发言列表和试听页，不运行模型：

```powershell
python -c "from alignment.b12_report import build; build('output/whisperx_b12/S01E02', 'output/wiki/season1/episodes/S01E02.json', batch_authorized=True)"
```

只生成两套数据的并排页（不推理、不修正现有 Wiki 对应或模型时间）：

```powershell
python build_source_comparison.py --episode S01E02
python build_source_comparison.py --all
```

左侧为合并 Wiki 前的 `result.whisperx.json`（含原 wav2vec2 词级对齐及说话人编号），可展开更早的 ASR 原始大段。右侧为现有 `utterances.json`，保留错误对应及异常；“定位左侧原始段”显示其引用来源。两侧的原始词索引共用，点击同一个词会同时高亮。S01E02 默认展示 41–55 秒争议区间，可切换查看整集。

## 耗时口径

- 季汇总 `elapsed_wall_seconds`：本次批次从启动到当前／结束的实际墙钟时间，包含输入与模型校验、共享加载、推理和报告。
- `shared_model_load_seconds`：各阶段共享模型加载时间，只计一次。
- 新处理单集的 `processing_wall_seconds`：该集各阶段活跃处理时间合计，不含共享加载和等待其他集数的时间；分项在 `timings`。
- `report_seconds`：关联 Wiki、导出试听音频和生成页面的时间。
- 复用的 S01E01 保留原有单集运行口径（包含当时模型加载），不计入本批次新推理耗时。
- 断点续跑后，季汇总墙钟时间从本次启动重新计时；逐集已保存的活跃处理耗时继续累计，不能把中断等待时间算成推理耗时。

不要把“有候选”“没有机械异常提示”或模型分数当成准确率。笑声错位、漏词、截尾等问题仍以试听为准，批次会保留所有异常供后续检查。
