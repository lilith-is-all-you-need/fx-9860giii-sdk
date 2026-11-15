# Loader Probe 2.1

面向 fx-9860GIII / SH7305 的下一轮实机探测。它加载配套的 `Probe2.bin`，
保留 G1A 容器和镜像布局，通过独立 RAM 中的恢复代码暂时替换原程序的
4 个代码/资源页与 2 个静态数据页。不是通用 Loader，也不加载未知第三方文件。

2.1 修复启动内存开销：16 KiB 结果文件只用 2 KiB 内存缓冲分段写入，
镜像与目标静态 RAM 共用一次 8 KiB 对齐预留，保留原探测项目。
分段写入保持偶数长度与偶数起始位置，并读回尾部核对；兼容读取 2.0 的结果。
另生成 1024 字节的 `P2Alloc.txt`，记录每次分配的大小、原始返回地址和失败原因。
该启动诊断使用栈内缓冲；失败后先释放已申请内存，再尝试写文件。
它会更新上次同格式诊断，但不会覆盖同名的外来文件。

## 放进计算器的文件

将发布包的 `Probe2.g1a`、`Probe2.bin`、`Probe2.cfg` 放到存储根目录。
结果由程序创建为 `Probe2.txt`；不覆盖上一版 `Probe.txt`。
从 2.0 升级时请同时替换 G1A、BIN、CFG 三份文件。
旧的 `Probe2.txt` 会保留并追加重入/退出记录，**不会自动重跑**。
要重新探测，先把该结果复制回电脑，再删除计算器上的 `Probe2.txt`。
请先备份计算器资料；本轮会改变临时地址映射，未通过的实机路径可能卡住或重启。

## 操作（两次运行覆盖两种退出路径）

第一轮测试菜单切换：

1. 启动 Probe2，等到 `Auto tests passed / MENU: switch app`。默认自动执行 8 轮。
2. 按实体 **MENU**，选回 **Probe2**，再按一次 **EXE**。这检查原程序恢复。
3. 再按 **MENU**，进入 **RUN-MAT** 等另一个应用，然后从菜单重新打开 Probe2。
4. 看到 `Saved: results ready` 或 `Saved: NEED REVIEW` 后按 **EXIT**。
5. 把生成的 `Probe2.txt` 复制到电脑，命名为 `Probe2-menu.txt`。

第二轮测试直接退出：

1. 确认第一轮文件已备份，删除计算器上的 `Probe2.txt`，重新打开 Probe2。
2. 自动检测完成后直接按 **EXIT**（F2 也走同一退出路径）。
3. 从菜单重新打开 Probe2，看到已保存结果后再按 **EXIT**。
4. 将这次 `Probe2.txt` 保存为 `Probe2-exit.txt`，两份一起回传。

若出现 `NEED REVIEW`、`File write failed`、卡住或重启，保留已有结果，
回传文件并说明停在哪个画面/按键。`Probe not run` 表示尚未执行映射测试，
第二行会提示配置、BIN 或内存问题。不要通过连续重跑覆盖失败现场。
若再次出现 `Probe not run`，先按 EXIT 正常退出，回传 `P2Alloc.txt`。
其中 `No heap: context / image/RAM / runner` 表示对应申请返回 NULL；
`address not P1` 表示非空地址不符合本探针要求。若显示 `Alloc log unavailable`，
说明连启动诊断也未成功保存，请记录屏幕两行错误。启动失败不等于映射测试失败。
菜单操作与 `Auto tests passed` 是不同阶段；自动通过并不等于菜单阶段通过。

## 记录内容与结论范围

- 固定配置、BIN 长度与校验、CPU/OS/栈地址、MMU/缓存寄存器。
- 未保护的临时映射经过 Sleep / 文件调用后的变化（对照组，不要求必然丢失）。
- 通过 URB 保护 6 个临时页，重复加载、初始化、执行、恢复。
- 资源跨页读取、远页函数调用、初始化数据、跨页 BSS、P0/P1 数据别名、OS 堆。
- 目标程序执行 Sleep 时，独立 RAM 内的定时器回调是否运行、映射是否变化。
- 目标退出函数、OS 退出回调、映射恢复、文件写入/尾部读回、再次启动。
- 每个危险阶段之前先写检查点；中途停止也能定位最后完成的阶段。

`Probe2.cfg` 为 ASCII 文本，仅允许 `image_bytes`、`image_fnv`、`loops`、
`hold_ms` 四项。默认循环 8 次；合法范围分别为 1–16 次与 160–2000 ms。
首次请保持默认。镜像长度和校验必须与配套 BIN 一致，不能换成 KhiCAS。

收到实机文件后才能判定上述路径是否成立。即使全部通过，也只证明这个
16 KiB 目标镜像、8 KiB 静态 RAM 和所测系统调用的 Loader 基础路径；
不证明 KhiCAS 的内存容量、无源码地址分析、全部 syscall、所有中断/外设和长期稳定性。
完整 OS 缺页处理、DMA、任意崩溃恢复、构造/析构兼容不在本探针中。

## 构建和验证

使用 Fx Studio 原生 SDK 打开本目录，先构建 Debug，再构建 Release。
`fxide.json` 选择 `probe2` 主目标；其依赖生成测试镜像。主目标链接后，
`tools/pack.py` 从保留的 ELF 重定位中提取常驻代码指针修正表，拒绝指向
常驻段外部的符号引用。源程序首部不删字节。

构建缓存目录（见 `.fxstudio/build/Release/artifact.json` 的 `cacheDirectory`）
中 `build/` 包含 `Probe2.g1a`、`Probe2.bin`、`Probe2.cfg`、
`probe2.resident.json` 和 `payload-manifest.json`。
`P2Target.container` 本身是 G1A，逐字节复制成 BIN，避免 IDE 将其误选为主产物。

```powershell
python probes/hardware-loader/tools/verify.py --bundle C:/bundle --emulator probes/emulator/build/FxEmulator.exe --output C:/new-empty-verification
python probes/hardware-loader/tools/inspect_result.py C:/returned/Probe2-menu.txt
```

集成回归默认限定 48 KiB 堆，覆盖 8/16 轮、两种退出路径、旧日志跨缓冲边界读取、
三处内存不足及文件保护，并检查实际调用的写入长度/定位均为偶数。
48 KiB 是保守测试预算，不是本次实机剩余堆的测量结果。

常驻代码通过 P2 执行；上下文、恢复栈与日志不在被替换的虚拟区。
镜像/静态 RAM 按 8 KiB 对齐，使缓存索引位 [12:5] 与目标虚拟地址一致；
复制后执行 OCBP、SYNCO、ICBI，替换映射时单独失效目标 ITLB。
仅使用当前空闲 UTLB 槽，保护数量不足时停止，不覆盖任意占用的保留槽。
退出回调在恢复原镜像后尾调用原程序释放函数，避免返回已释放的 RAM。
若定时器注销失败则记录失败并保留回调所需分配，避免释放仍可能执行的代码；
这种结果需分析后再重启清理，不作为成功。

模拟器验证使用 HLE；其中菜单恢复/替换时机与 OS 缺页重填仍是待实机核对的模型。
操作数缓存采用一致内存近似，不模拟 copy-back 脏行或总线写回时序。
`CCR=0x105` 不能解释成 write-through；一次没有看到延迟不等于不存在写回要求。
参考：[Renesas SH4AL-DSP 软件手册，第 7–8 章](https://www.renesas.com/en/document/mas/sh4al-dsp-software-manual)。
