# 原生 Windows SuperH 预览与调试后端

本目录已实现可运行的 `FxEmulator.exe`，直接装载 `.g1a` 中的 SuperH 指令。没有将计算器源码重编译成 PC 程序。界面、数学计算和按键处理均由被加载的 G1A 执行。

## 来源与结构

- 基础解释器：`third_party/emuCasioCalc`，上游 `https://github.com/joserodpt/emuCasioCalc`。
- 固定提交：`63e325708e9eea53eb4769b9c057082614ebd919`。
- 上游 MIT 许可证须随包保留；OS 文本使用的 Spleen / Unifont 字体许可证在上游 `assets/fonts/`。
- 使用 CPU、内存、SH7305、T6K11 以及系统调用模拟源码；没有链接 SDL 或 Casio 官方 SDK / OS 镜像。
- `prepare_sources.py` 在 `build/patched/` 生成调试钩子副本，并生成 `debugger-hooks.patch`。原上游源码不改动。
- `bridge.c` 实现仅监听 `127.0.0.1` 的 GDB Remote Serial Protocol 与控制协议；`bridge_platform.c` 提供显示、按键和字符适配。
- `compat.h` 适配 Windows 的 `mkdir`、`localtime_s`；`bridge_compat.h` 将路径统一视为 UTF-8，转成宽字符 `fopen`。

## 构建

运行 `build-bridge.ps1`。本机验证所用编译器为 MinGW GCC 15.1.0，路径 `C:\msys64\mingw64\bin\gcc.exe`。构建脚本需要 Python 3。启动已编译后端不需要 Python、MinGW 或 WSL。

输出为 `build/FxEmulator.exe`，当前带原生调试符号约 1.70 MB，动态导入仅有 Windows 自带的 `KERNEL32.dll`、`msvcrt.dll`、`WS2_32.dll`。编译过程使用相对 ASCII 源文件/输出路径，避免 MinGW 链接器对中文绝对路径的处理问题；用户运行时路径已用宽字符 API 实测。

## 运行协议

```text
FxEmulator.exe --gdb-port 0 --control-port 0 --framebuffer "绝对路径.bmp" "插件.g1a"
```

端口为 0 时自动分配。启动成功后 stdout 输出一行：

```json
{"event":"ready","gdbPort":12345,"controlPort":12346}
```

此时程序停在 `0x00300200` 的入口，模拟时间为零，尚未执行任何插件指令。GDB 应使用 `set architecture sh4al-dsp`、`set endian big`，随后连接所给端口，并载入与 G1A **配对**的未剥离 ELF。后端不负责加载 ELF 或猜测符号对应关系。

控制端口是持续 TCP 连接上的逐行 UTF-8 JSON，每请求返回一行 JSON：

```json
{"command":"status"}
{"command":"key","key":"EXE","down":true}
{"command":"key","key":"EXE","down":false}
{"command":"quit"}
```

状态包含 `state` (`paused` / `running` / `exited` / `error`)、`pc`（8 位十六进制）、`cycles`、`reason`、`error`。支持的键名以 `src/utils/keys.c` 为准，包括数字、F1–F6、EXE、EXIT、MENU、SHIFT、ALPHA、AC、DEL、方向键、PLUS、MINUS、MULT、DIV、DP 等。未知键或未知命令返回 `ok:false`。

屏幕是 128×64、24 位 BMP，先写同目录临时文件再原子替换；运行时最多约 15 帧/秒。断点、单步或中断停下时，在发送 GDB 停止通知前强制读取并刷新当前硬件 framebuffer，不额外执行目标指令。UI 应打开并读取文件后立即释放文件句柄，以便原子替换。首次 continue 前不存在画面是正常的。路径不可写时后端启动失败，不宣称已 ready。退出时使用有界 socket linger，让最后的控制回复在 Winsock 清理前发送完毕。

## 调试语义

- 软件/硬件地址断点由解释器在执行目标指令前精确检查，不修改代码。
- 指令单步覆盖分支延迟槽；可在延迟槽内暂停、检查并恢复。处于延迟槽时改 PC 返回错误，以免破坏已锁存的分支目标。
- 读、写、读写观察点由实际访存钩子捕获，在该访存指令完成后报告。
- GDB 内存读取只读取普通映射页，不触发 MMIO，避免查看内存造成设备副作用；MMIO/未映射地址明确返回错误。
- 常用通用寄存器、控制寄存器及非活动寄存器银行可读写。不实现的 DSP/FPU 寄存器返回不可用值，而不是伪造为零。
- 暂停发生在同步调试事件泵中，保留解释器的 C 调用栈。因此可在 HLE 系统调用所执行的客户回调内暂停，不使用丢弃调用栈的长跳。
- 暂停不推进 CPU 周期/模拟时钟。异步 Ctrl-C 可以中断运行。
- 断开 GDB 会暂停目标并清理该连接的断点。所有监听均局限本机回环地址。
- 运行每片约 10ms，尽量贴近实时；并不声明周期精确或真实硬件速度精确。

## 已执行的验证

`test_bridge.py` 当前共 55 项集成检查通过，完整结果在 `build/bridge-test.json`：

- 使用包含中文和空格的 G1A 路径及 BMP 路径启动。
- 初始入口、寄存器包、内存访问、不可用 MMIO、非法断点错误。
- 真实 SH 指令执行、寄存器/内存写入、读/写观察点、延迟槽断点与恢复。
- 异步暂停、暂停时间冻结、键盘控制和正常退出。
- 错误校验和、溢出地址/长度、畸形内存写请求、重复 JSON 字段和非法控制消息的拒绝。
- 加载原始 CAS02 G1A，通过控制端口键入 `2+2`、按 EXE；得到 `=4`。最终屏幕前景像素与已经目视确认的独立执行结果逐像素一致。

`test_gdb.py` 使用本机真正的 `gdb-multiarch.exe` 连接后端，已验证反汇编、`stepi`、寄存器及内存修改、断点 continue、读/写观察点以及 `$r0==3` 条件断点。记录在 `build/gdb-real.log`。其中检查指令序列通过 GDB 写入目标模拟 RAM，测试的是 SH CPU 与 GDB 控制行为，不是 PC 函数。

`test_source_debug.py` 对 **CAS01 历史发布件**完成了源码层验证。`audit/compact-cas/target/khicas_next` 的三个非空 ELF PT_LOAD 段，与 CAS01 的 105,288 字节 G1A payload 全部逐字节相同，证据为 `build/cas01-pairing.json`。它不匹配 CAS02，因此没有混用。应用源码取自 CAS01 的发布快照。

该源码测试实际在 `main:62` 停住、读取 `key_options=468`、`next` 至第 63 行；在 `ui_draw:766` 停住、读取 `ui->input[0]=0` 和 `ui->notice="Starting CAS"`；调用栈显示 `ui_draw → main`；`next/step` 至第 767/772 行，`finish` 正确返回 `main:78`。完整输出见 `build/gdb-source.log`。此历史包使用 `-Os`/LTO，部分变量正常显示 `<optimized out>`；新项目应提供独立的 `-Og -g3` Debug 配置。Gint 库源码原路径不在该快照内，其源码行可能无法打开，但应用源码行可打开。

带调试钩子的 CPU 源码运行上游 `tests/test_cpu.c` 全部通过，覆盖除法、进位、call/延迟槽、循环、移位、乘法、DSP repeat、TRAPA/RTE 寄存器银行和 MOVUA。记录在 `build/test-cpu.log`。

`test_native_examples.py` 已对本次 **Windows 原生工具链新编译**的 `counter-c` 和 `counter-cpp` 的 Debug/Release 四份产物完成真实 G1A 执行验证。测试先核对构建 manifest 的 ELF/G1A SHA-256，再启动原生 GDB 16.3 与模拟器；没有回退到历史 KhiCAS 文件。

两种 Debug 版本均通过：main 断点、next 完成初始画面、真实 PLUS 键触发 change_counter 断点、参数 delta=1、C 指针/C++ 引用、局部 previous=0、step 进入 clamp_counter、三层调用栈、两次 finish 返回 main、寄存器和内存检查、counter.value=1 与 updates=1、更新后的屏幕。Release 版本通过入口断点、实际按键、原始内存状态及屏幕变化检查，不假称 Release 带应用 DWARF。共 18 组检查的结果、四份 MI 日志及四组初始/更新截图在 `build/native-examples/`；C++ Debug 更新画面已目视确认显示 Counter: 1、Updates: 1。

初始无调试探针 `preview-probe.exe` 还直接执行了 CAS02 的 106,568 字节 G1A：61,931,102 模拟周期、5 次显示更新、全部按键脚本步骤消费，无 CPU 错误。图像为 `build/initial.png` 和 `build/calculated.png`；正式后端截图为 `build/live-initial.png` 和 `build/live-calculated.png`。

## 边界

这是 GIII 类 SH7305/128×64 显示与部分系统调用的模拟器，并不是完整 Casio OS。采用上游 `MODEL_FX9750G3`（上游代码注明同属 fx-9860GIII / Graph 35+E II）。菜单内置应用、USB、DSP 算术指令等上游未模拟部分仍不可用；未知系统调用会报错。OS 文本替代字体可能与实机不同，gint 自带字体则由目标代码绘制。

“断点、变量、调用栈可用”与“所有硬件行为精确”是不同验收项。通过此处测试不等于所有 G1A、所有外设、所有 OS 版本或真机都已验证。原生工具链的 C/C++ 四种样例已单独通过上述验证；真机安装仍需实机验收。历史 CAS01 与本次新编译样例的证据分别保留。
