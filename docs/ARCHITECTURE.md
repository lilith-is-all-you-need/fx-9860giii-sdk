# Fx Studio：实现约定与验收标准

2026-11-14。面向 Windows 10 x64（19041 或以上），中文/英文，可对外分发，安装及日常开发离线。用户明确要求直接实现可运行 IDE；预览必须执行 SuperH 编译产物并与源码调试联动。没有接入真机，真机测试不能以仿真替代。

## 组件

0.2.0 增加独立的 `FxStudio.Automation` 会话/命令领域层和
`FxStudio.Agent` MCP stdio 适配器。四个稳定外层工具通过有独立版本和
参数 schema 的命令目录扩展功能；操作重试、取消、事件游标和状态一致性
约定见 [AUTOMATION.md](AUTOMATION.md)。当前自动化与 WPF 拥有独立会话，
没有宣称可以接管桌面已打开的会话。资源与 syscall 边界见
[能力核验](SDK-CAPABILITIES.zh-CN.html)。

- **桌面界面**：WPF / .NET 10，自包含发布；AvalonEdit 代码编辑器。使用 Windows 控件、浅色面板和轻量 Fluent 风格，不包含浏览器内核。编辑器、工程树、构建诊断、128×64 屏幕、键盘、断点、局部变量、观察表达式、调用栈、寄存器、内存和反汇编在同一窗口。
- **构建服务**：默认使用完整原生 Windows 工具链；独立 WSL 后端保留为可选实现。本机 WSL 服务无法恢复后，实际重建了 MinGW 宿主的 GCC 14.1 / binutils 2.42，移植 fxSDK 2.11 主机工具，并保留固定 gint、fxlibc、OpenLibm、libstdc++ 目标库。CMake 工作流不变，Debug/Release 分目录，用户源码经 ASCII 缓存暂存，支持中文工程目录。0.1.1对无可用短路径的SDK安装自动创建按内容分隔、逐文件SHA-256校验的ASCII快照，首次约400MB，后续复用；SDK更新不会沿用旧编译缓存。构建缓存自身仍需ASCII路径或可用短路径。Debug 用户对象使用 `-Og -g3 -fno-lto`；最终链接仍处理 SDK 的 LTO 库，原生链接固定 `-flto-partition=none`，避免 GCC14.1 在跨宿主 zlib/zstd 压缩流间生成不兼容中间分区。SDK 库自身仍可能优化。
- **模拟器**：基于 MIT 许可 emuCasioCalc 的 Windows 原生后端，直接执行 `.g1a` 的 SH7305 指令并模拟屏幕、键盘与所支持外设。采用 GIII 配置；不会包含 Casio ROM。上游未支持的 OS 调用/外设明确报错，不伪造通过。
- **调试服务**：Windows 原生 GDB 多架构版，IDE 使用 MI2，模拟器实现 GDB remote protocol。ELF 提供符号，G1A 提供实际执行字节；二者必须来自同次构建。
- **离线发行**：IDE 自包含运行时、模拟器、原生 GDB、原生编译工具链、Python/Pillow/CMake/Ninja、示例、许可证、对应源码与校验清单。无需 WSL 安装和服务。未验证的 WSL rootfs 不纳入已完成发行。官方 SDK 只作研究参考，不作为运行依赖或再分发内容。

## 进程边界

```
WPF IDE ── Process.ArgumentList ── Native Python / build-native ── CMake + GCC ── ELF + G1A
   │
   ├── GDB/MI2 ── GDB ── loopback GDB RSP ── SuperH 模拟器
   └── loopback JSON control + BMP framebuffer ── 同一个模拟器进程
```

GDB 和模拟器都是独立进程。端口仅绑定 127.0.0.1，默认自动分配。IDE 关闭、停止或异常退出时清理自己启动的子进程，不结束其他开发任务。构建命令用参数数组，不拼接包含工程路径的 shell 命令。中文、空格、单引号路径纳入验收。

## 模拟器协议

启动参数：`<g1a> --gdb-port 0 --control-port 0 --framebuffer <absolute.bmp>`。初始暂停于入口，stdout 一行 ready JSON 提供 `gdbPort` / `controlPort`。控制端每行一个 JSON 请求/响应：`{"command":"key","key":"EXE","down":true}`、`{"command":"status"}`、`{"command":"quit"}`。状态包含 CPU 错误、运行/暂停状态和 PC。BMP 为原子替换的真实 framebuffer；暂停不清空最后屏幕。协议最终实现有调整时更新本文与 Core README。

## 调试验收

1. 同一示例生成 C 和 C++ G1A，文件头、CPU架构、内存与大小检查通过。
2. 实际 ELF/G1A 配对加载；在用户源码行停下，单步进入、单步越过、跳出、继续、暂停、重启可工作。
3. 局部变量、全局/观察表达式、调用栈、寄存器、内存、反汇编从目标读出；条件断点/读写监视点按实际支持验证。不可用项明确显示原因。
4. 按键改变目标程序变量与屏幕，屏幕变化与同一调试会话一致。中断与模拟时间暂停语义正确。
5. CPU 错误、未知 syscall、编译失败、错误路径、调试器退出、取消和端口冲突必须报告，不保留旧成功状态。
6. 完整原生包搬到新目录，用仅 Windows 系统 PATH、拒绝联网的代理和随包工具构建示例。不依赖全局 MSYS、Python、CMake、.NET SDK 或 WSL。代理测试不等于断开网络接口；安装包不得包含需要下载的恢复步骤。WSL 单独导入验证仍未完成，不作为原生包验收的替代。
7. 自包含 IDE 在未安装开发 SDK 的环境启动；本机 CUA 对编辑、构建、预览、断点调试进行验证。

## 边界

“完整调试”在这里指模拟器上的实际 SuperH 程序调试能力，绝不等于完整 Casio OS/所有外设仿真。真实设备的识别、启动、OS 版本和硬件行为需要最终人工实测。现有 KhiCAS 大型 Giac 构建的体积问题不在 IDE 内自动解决；IDE 必须报告超限，而不能把链接成功等同可安装。

官方 SDK 的 CHM 已用于核对窗口/快捷键/断点类型。其默认编译参数为 `-cpu=sh3`，不能直接视为 GIII 全兼容后端。CUA 对该旧程序的窗口截图两次超时，未用猜测坐标操作；无需为功能调查反编译专有程序。
