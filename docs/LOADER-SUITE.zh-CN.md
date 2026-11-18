# FxStudio 普通 G1A 加载手册

[English](LOADER-SUITE.en.md) · [超限 Loader 源码示例](../sdk/examples/oversized-loader/README.zh-CN.md)

FxStudio 接收完整的普通 G1A，或仅改了后缀的同一镜像。**上限为 2,097,152 字节，包含文件头。** 恰好达到上限仍可进入常规分析。超过上限会直接显示输入大小和示例路径，开启 Ghidra 也使用相同边界。有源码且需要超限的项目可以单独构建上方示例。

这个数值是已有镜像的加载窗口。SDK 从 C/C++ 工程构建并校验可部署 G1A 时另有 2,000,000 字节的保守预算，见 [构建校验](../tooling/build-project.py)。示例先构建两个很小的 G1A，再为测试程序生成大于窗口的外部数据文件。

## 准备与安装

在「工具 → 为 Loader 准备 G1A」中选择输入和输出位置。默认每个输入生成一个以名称加短 SHA 命名的目录。可勾选附带启动器。WinUI 版还可以单独导出启动器。脚本或 LLM 可从 SDK 根目录调用同一引擎：

~~~powershell
python tooling/profile_job.py generate --input game.g1a --output-root results
python tooling/profile_job.py generate --input game.g1a --output-root with-launcher --include-loader --artifacts loader-artifacts
python tooling/profile_job.py export-loader --backend flash --output launchers --artifacts loader-artifacts
~~~

将结果中 `calculator` 的内容合并到计算器存储根目录。保留 `FXAPPS/<ID>/` 下的所有文件。普通程序（含原版 KhiCAS）默认由公共 `FlashLd.g1a` 启动。仅在显式指定 `--backend mapped`、复现旧版 KhiCAS 测试时使用 `KLoad.g1a`。所需启动器见 `analysis.json` 的 `requiredLoader`。首次在 FlashLd 使用 Full，Fast 会复用校验，可能漏检两次运行间的同大小改写。

## 接口速查

| 问题 | 入口或结果 |
| --- | --- |
| 自动调用和退出码 | [profile_job.py](../tooling/profile_job.py) 的 `generate` 与 `export-loader`。生成任务返回 0 表示程序目录就绪，2 表示生成报告但仍需复核，1 表示处理错误。CLI 用独立 JSON 行报告进度与错误。 |
| 哪些文件可以交给用户测试？ | `job-result.json` 的 `programReady` 表示目录齐备，`includesLoader` 表示附带启动器。`hardwareValidated` 单独记录实机状态。读取 `diagnostics`、`blockers` 与 `deepAnalysis.status` 可区分镜像问题和 Ghidra 执行问题。 |
| 快照、返回调用者、MENU 策略 | [调用者会话说明](../sdk/caller-session/README.zh-CN.md) 与 [fx_caller_session.h](../sdk/caller-session/include/fx_caller_session.h)。查 `fxcs_init`、`fxcs_prepare`、`fxcs_handoff`、`fxcs_recover` 和 `fxcs_error_text`。接入方保存业务状态。当前通用 Flash 启动器缺少恢复任意调用者的后端。 |
| 日志和实机诊断 | [FlashLd 目录与日志](../probes/storage-loader/FOLDERS.zh-CN.md)。异常后先保留对应目录的 `RUN.LOG`，记录最后按键及屏幕。历史实机证据见 [踩坑手册](loader/handbook/PITFALLS.zh-CN.txt)。 |
| 如何开发超限源码项目？ | [独立示例的构建、API 和容量限制](../sdk/examples/oversized-loader/README.zh-CN.md)。运行库由示例项目显式引入。 |

模拟器覆盖、静态分析结果和实机运行记录分别描述不同的证据。评估一个新程序时，分别记录启动、保存、退出和直接 MENU 选回。独立发布的 FX Universal Loader 有自己的版本和支持范围。
