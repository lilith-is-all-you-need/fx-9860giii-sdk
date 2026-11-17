# Loader 两端套件与项目拆分

本轮提供电脑端统一分析/打包、计算器端 RAM Loader、原版 KhiCAS 映射
Loader、源码接入的 699 页 Giac Loader，以及修正后的模拟器。
**自动适配只覆盖审核过的精确版本，不保证大多数未知 G1A 无人干预运行。**

2026-11-17 实机反馈：两种 CAS 首次运行可用，MENU 后直接选回同一个 Loader
停在疑似 Loading。Giac RC2 已补结束页和 EXE 重新加载，模拟器复测通过、实机
仍待复测；原版 KhiCAS 的这个实机问题尚未复现。Fruit/Minesweeper 的 RAM
镜像申请失败，当前转换器已阻止继续生成这两个 RAM 安装包。

FxStudio 的“工具 → 为 Loader 准备 G1A”选择输入和新的输出目录。
“帮助 → 计算器资料”提供可搜索的软硬件事实、证据级别和 syscall 覆盖。
内容嵌入程序，不需要联网。输出中的 `calculator` 才是安装文件；其余
`analysis.json`、逐页校验和及 profile 供电脑端复核。

## 后端与边界

| 后端 | 输入/入口 | 状态 |
| --- | --- | --- |
| RAM | ≤160 KiB 镜像，Loader.g1a | 这是实现上限；Fruit 的 77,823 B 和 Mines 的 135,167 B 连续申请已在实机失败 |
| 原 OS 映射 | 原版 2,094,444 B KhiCAS，KLoad.g1a | 首次运行实机可用；直接选回未通过，启动时明确提示 |
| 扩展映射 | 已源码接入的 2,859,236 B Giac，KhiMap.g1a | RC1 首次运行实机可用；RC2 加结束提示和明确重新加载，实机复测待完成 |
| 未知程序 | 未审核 SHA、未分类网关、内存/回调关系不明 | 生成报告并列出缺项，不生成可执行成功结论 |

原版 KLoad 的目标计算 arena 缩为 106 KiB。新 KhiMap 使用 32 KiB arena，
数学跟踪预算为 24 KiB；它与原版不是同一数学/UI 构建，不能直接比较功能或
把 699 页成功推广到所有二进制。当前 KhiMap 禁止运行中的文件操作、OS
定时/退出回调注册和直接重启；MENU/OFF 先清理后交还系统。部分半初始化
故障仍可能需要 RESET。它显示失败阶段，不写运行结果文件。

原 BIN 不做统一地址差分、不删除头部。普通 G1A 保留原始所有字节；Giac
输入则是源码接入工程已经生成并校验的私有头 BIN。物理 Flash 地址必须在
计算器上实时查询，电脑 profile 保存文件偏移、校验和、接口及限制。

命令行无需 LLM 或网络：

```powershell
python tooling/loader_suite.py input.g1a --output new-result
python tooling/loader_suite.py --batch jobs.json --artifacts loader-artifacts
```

`--profile auto|ram|mapped|extended` 指定后端；错误的容量组合会拒绝。
`--review-profile` 接受绑定 SHA 的审核数据，不执行任意插件脚本。
返回 0 为可测试候选、2 为报告/profile 尚需适配或补充启动器、1 为输入错误。
完整包还核对启动器文件的 build manifest；扩展 Giac 再检查审核过的启动器 SHA。

## 独立公开项目

* [fx9860-emulator](https://github.com/lilith-is-all-you-need/fx9860-emulator)：模拟器、CPU/系统调用/MMU 回归、故障留档与协议。
* [fx9860-loader](https://github.com/lilith-is-all-you-need/fx9860-loader)：统一电脑端工具、版本注册表、RAM Loader。
* [fx9860-large-loader](https://github.com/lilith-is-all-you-need/fx9860-large-loader)：原版 KhiCAS 映射、698 页探测、699 页 Giac 启动器和运行库接口。

FxStudio 保留离线源码快照，`loader-components.lock.json` 绑定各仓库提交及文件
哈希；`python tooling/check_loader_components.py` 检查一致性。共享编码器和
OS 识别头按版本保留，禁止把不同版本副本混写。后续组件维护在对应仓库进行，
同步快照后更新锁文件并运行回归。固件、第三方原始 G1A、数学归档不上传这些仓库。

最初证据汇总在 `loader-suite-validation.json`；最新 MENU/内存结果见
`probes/extended-cas/VALIDATION-REENTRY-20261117.json` 和 `profiles/hardware-results-20261117.json`。
模拟器新增 guest VBR 缺页转交、
故障前寄存器恢复、1024 页文件碎片记录；OS 自身仍保持 512 页。
模拟器仍是 HLE，无完整 copy-back D-cache、外设时序及真实 OS 菜单生命周期。
断言、截图和实机记录分别说明其能证明的范围。
