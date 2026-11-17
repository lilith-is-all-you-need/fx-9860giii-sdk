# FX Universal Loader 与 FxStudio 集成

FxProfile 和计算器端启动器共用一个版本。可从[统一项目的 Releases 页](https://github.com/lilith-is-all-you-need/fx_universal_loader/releases)下载。

## 2026-11-18 目录版与动态页表

本节为当前接口，下文旧版记录仅说明历史证据，不能用于安装新版目录包。
英文说明见 [LOADER-SUITE.en.md](LOADER-SUITE.en.md)。

- FX Profile Studio 0.2 支持中文/English 切换。默认生成“原名＋短 SHA”目录，
  只含程序依赖；可以勾选附带 Loader，也可以不选输入文件而单独导出 Loader。
- 安装时合并 `calculator` 内容到计算器存储根目录，保留 `FXAPPS/<程序ID>/`
  层级。计算器目录 ID 是名称前缀＋短 hash，受系统八字符限制；电脑目录保留较长名称。
  每个程序有自己的 `IMAGE.BIN`、profile、`APP.MET`、图标及适用的日志。
- 公共 `FlashLd.g1a` 提供英文图标列表。默认 Full；可显式启用 Fast。
  只有本机完整校验成功写出的缓存才能加速。每次仍查询真实页地址；本次运行后续发现
  地址变化才重新校验。Fast 不保证发现两次启动之间同大小的内容改动；修改 BIN 后使用 Full。
- `ExtLoad.g1a` 从 `EXT.PRF` 读取真实镜像长度和页数，不再按 699 页编译。
  `pageCount=ceil(imageBytes/4096)`；`pageCapacity` 可留表项余量，未用项保持无效。
  原 OS 的 512 项表不扩写。另检查存储剩余量及常驻内存申请，失败时拒绝执行。
  当前 768 项和 3,000,000 B 包预算是实现策略，不是对机器可用容量的保证。
- 原版 KhiCAS 继续使用单独的 `KLoad.g1a` 内存池适配器；不能把它改用通用
  Flash 后端就视为具有相同的内存共存保障。源码接入的 Giac 使用扩展 ABI。

命令行与 WinUI 使用同一引擎，无需 LLM：

```powershell
python tooling/profile_job.py generate --input program.g1a --output-root results
python tooling/profile_job.py generate --input program.g1a --output-root with-loader --include-loader --artifacts loader-artifacts
python tooling/profile_job.py export-loader --output launchers --artifacts loader-artifacts
```

`program-ready` 表示依赖就绪，配合公共启动器使用；`candidate` 表示还附带匹配的
启动器，二者均未认证实机稳定性。`needs-adapter` 表示缺运行库适配，`analysis-incomplete`
表示所请求的 Ghidra 分析未完成。旧 `loader_suite.py` CLI 保留历史平铺格式，
新项目使用 `profile_job.py`。

异常 Hook 可以用于让源码运行库把缺页异常转交常驻补页函数，其他异常仍按明确
的原处理器约定分发。Ghidra 导出原始指令字节、VBR/控制寄存器相关位置、延迟槽、
函数和已恢复的跳转目标；`hook-review.json` 再核对这些位置与 BIN 的字节。
这些证据不自动生成可执行二进制补丁。未知运行库的所有 VBR 写入、异常栈、
寄存器保存、回调及退出恢复仍须完成适配；EXT v2 拒绝非零未知 Hook 记录。

源码可链接 `FxStudio::LargeRuntime`；调用方业务会话库位于 `sdk/caller-session`。
后者实现事务快照和两种 MENU 策略，但目前没有替任意 A 保留栈/堆并恢复的通用
Flash 后端。缺能力时在暂停 A、写快照之前返回不支持。嵌套 A→B→C 也拒绝。
旧 SH3 Add-in 在 GIII 上的兼容性仍按 MMIO、OS 调用、运行库分别分析，不能仅靠
共享 SuperH 指令集保证运行；研究记录见 `loader/design/`。

新构建仍须实机回传验收；历史“CAS 首次可用、MENU 选回失败”不等于新目录版已验证。

## 旧版实现及实机证据（归档）

本套件提供电脑端统一分析/打包、通用 Flash Loader、可选 RAM Loader、原版
KhiCAS 适配器、源码接入的 699 页 Giac Loader，以及模拟器。

2026-11-18 新增精选研究手册：[中文开发手册](loader/handbook/DEVELOPER-GUIDE.zh-CN.txt)、
[English developer guide](loader/handbook/DEVELOPER-GUIDE.en.txt)、
[中文踩坑手册](loader/handbook/PITFALLS.zh-CN.txt)、[English pitfalls](loader/handbook/PITFALLS.en.txt)。
其中区分实机、模拟器、反汇编与推断，避免把旧阶段结论当成现行能力。
[新版需求与验收基线](loader/design/requirements-20261118.zh-CN.txt)描述目录包、
可返回调用者的库、MENU 策略、启动加速与旧 SH3 适配目标；交付状态以上方当前接口为准。

**普通 G1A 的自动打包不再依赖程序名单，但仍不能保证所有 G1A 兼容。**
`FlashLd.g1a` 保留完整镜像、原始入口和初始化，只把需修改网关的页面放入 RAM。
启动、交互、退出和实机稳定性分别记录，不能把静态检查通过当成全部通过。

2026-11-17 实机反馈：两种 CAS 首次运行可用，MENU 后直接选回同一个 Loader
停在疑似 Loading。Giac RC2 已补结束页和 EXE 重新加载，模拟器复测通过、实机
仍待复测；原版 KhiCAS 的这个实机问题尚未复现。Fruit/Minesweeper 的 RAM
镜像申请失败，当前转换器已阻止继续生成这两个 RAM 安装包。

FxStudio 的“工具 → 为 Loader 准备 G1A”选择输入和新的输出目录。
“帮助 → 计算器资料”提供可搜索的软硬件事实、证据级别和 syscall 覆盖。
内容嵌入程序，不需要联网。输出中的 `calculator` 才是安装文件；其余
`analysis.json`、逐页校验和及 profile 供电脑端复核。

另有独立的 [FX Profile Studio（WinUI 3）](../desktop/ProfileStudio/README.zh-CN.md)：
支持批量导入、生成测试包、逐页分析以及可选 Ghidra 无界面深度分析。
Ghidra 导出实际引用、函数与反编译样本，不自动授权新补丁。未知超限文件仍明确
显示“需要运行时适配”；电脑端页表分析不能替代计算器上的物理页查询和补页异常处理。
本机已完成实际 WinUI 批处理、Tetris/KhiCAS/Giac 深度分析与取消任务验证，
记录在 `desktop/ProfileStudio/VALIDATION.json`。此次新增的是电脑工具，不是新的实机稳定性结论。

## 后端与边界

| 后端 | 输入/入口 | 状态 |
| --- | --- | --- |
| 通用 Flash（默认） | ≤2 MiB 普通 G1A，FlashLd.g1a | 无程序 SHA 白名单；自动识别网关并按需分配影子页。首次实机验证待完成 |
| RAM | ≤160 KiB 镜像，Loader.g1a | 这是实现上限；Fruit 的 77,823 B 和 Mines 的 135,167 B 连续申请已在实机失败 |
| 原 OS 映射 | 原版 2,094,444 B KhiCAS，KLoad.g1a | 首次运行实机可用；直接选回未通过，启动时明确提示 |
| 扩展映射 | 已源码接入的 2,859,236 B Giac，KhiMap.g1a | RC1 首次运行实机可用；RC2 加结束提示和明确重新加载，实机复测待完成 |
| 不支持的结构 | 未分类网关、识别出的直接复位跳转、超限镜像等 | 列出阻塞原因；未检出的动态内存/回调风险仍可能在运行时出现 |

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

`--profile auto|flash|ram|mapped|extended` 指定后端；错误的容量组合会拒绝。
auto 为普通 G1A 选择 flash；精确原版 KhiCAS 保留原内存池适配器，超限 Giac
仍使用其源码接入协议。可用 flash 显式进行实验，但不自动修改目标私有堆大小。
`--review-profile` 接受绑定 SHA 的审核数据，不执行任意插件脚本。
返回 0 为可测试候选、2 为报告/profile 尚需适配或补充启动器、1 为输入错误。
完整包还核对启动器文件的 build manifest；扩展 Giac 再检查审核过的启动器 SHA。

## 下载与源码同步

* [fx9860-emulator](https://github.com/lilith-is-all-you-need/fx9860-emulator)：模拟器、CPU/系统调用/MMU 回归、故障留档与协议。
* FxProfile 桌面包内含配套启动器。只需要拷贝启动器时，可选择计算器包，其中包含 FlashLd、ExtLoad 和原版 KhiCAS 专用的 KLoad。[FX Universal Loader 下载](https://github.com/lilith-is-all-you-need/fx_universal_loader/releases)

FxStudio 的 `loader-components.lock.json` 用同一个提交锁定 FxProfile 和计算器端源码，
模拟器单独锁定。维护者在统一仓库检出对应版本后，可从 SDK 运行
`python tooling/sync_loader_components.py --universal-loader 统一仓库路径` 同步快照，
再用 `python tooling/check_loader_components.py` 校验。现有工程继续通过
`sdk/caller-session` 和 `sdk/fxlarge` 引入两个运行库。

最初证据汇总在 `loader-suite-validation.json`；最新 MENU/内存结果见
`probes/extended-cas/VALIDATION-REENTRY-20261117.json` 和 `profiles/hardware-results-20261117.json`。
模拟器新增 guest VBR 缺页转交、
故障前寄存器恢复、1024 页文件碎片记录；OS 自身仍保持 512 页。
模拟器仍是 HLE，无完整 copy-back D-cache、外设时序及真实 OS 菜单生命周期。
断言、截图和实机记录分别说明其能证明的范围。

通用加载器的最新验证见 `probes/storage-loader/VALIDATION.json`。将新测试包
calculator 中所有文件放入存储根目录，保留 FlashLd.g1a 名称；UP/DOWN 选择、
EXE 运行，结果写入 FlashLd.txt。首次验证建议先进入 RUN-MAT，再重新启动
FlashLd 测试下一项，避免把旧会话恢复与新启动混淆。
