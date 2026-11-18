# 源码仓库说明

本仓库保存 Python 脚本、测试、运行配置和项目说明，不发布任何视频、音频、模型权重、虚拟环境、Wiki 正文采集或生成结果。

常用入口：

- `run_season_b12.py`：按固定 B12 配置批量处理，支持断点续跑。
- `build_source_comparison.py`：将原始模型输出与 Wiki 对应结果并排试听，不重跑模型或修正原数据。
- `verify_season_b12.py`：检查输出完整性及词时间是否原样保留。
- `BATCH_SEASON1.md`：第一季运行方法、输入目录、输出结构和耗时口径。
- `configs/whisperx_b12.fixed.json`：已确认运行的完整配置快照，包含原机器路径和校验值，不可隐式改写。

克隆仓库后，需自行准备文档指定的输入、模型和 Python 环境。不要从仓库中的历史耗时或完整性统计推断所有音频边界已经通过人工听验。

`tests/` 中的算法／合成数据测试可独立执行；需要本机已生成结果或采集页面的测试，在这些本地数据不存在时会明确跳过。测试依赖见 `requirements-wiki.txt` 及相应流程环境说明。

`alignment/vendor/nemo_forced_aligner/` 保留 NVIDIA NeMo 2.5.3 的脚本、原版权头和 Apache-2.0 许可证；文件来源与校验信息见该目录 `source_listing.json`。不为第三方代码另行更改许可。
