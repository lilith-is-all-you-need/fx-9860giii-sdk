# 离线构建服务约定

## 当前默认：原生 Windows（0.2.0）

正常安装和使用不依赖 WSL。原生入口为：

```text
<SDK>/host/python/python.exe <SDK>/service/build-native.py SDK SOURCE BUILD Debug|Release
```

参数为独立参数，不拼接 shell 命令；SDK/SOURCE/BUILD 使用 Windows 绝对路径。
SDK 是发行包的 `sdk/native`。构建产物目录由调用者选择，不能等于或包含源码根。
工具链随包固定，CMake/fxconv/fxgxa/Python 都从 SDK 内定位，不需要全局 PATH。
中文 SDK 安装目录会生成内容校验的 ASCII 缓存，中文源码目录也会被暂存；
构建缓存根自身需 ASCII 路径或 Windows 可用短文件名。

Debug 用户对象为 `-Og -g3 -fno-omit-frame-pointer -fno-lto`，最终链接
处理预编译 SDK 的 LTO 对象并固定 `-flto-partition=none`。
SDK 库内部仍可能保留优化，不能据此承诺所有库函数的逐行调试体验。

`BUILD/artifact.json` 使用 `schemaVersion:1`、`pathStyle:"windows"`，
包含 ELF/G1A 的 Windows 绝对路径、源路径映射、SHA-256、配置和配对验证信息。
每次构建先撤销旧清单，失败不保留旧成功结果；同输出目录互斥，取消终止本次
拥有的编译进程树。`compile_commands.json` 和编译输出可供工具使用。
机器可读的会话/构建/调试入口见 [`AUTOMATION.md`](../docs/AUTOMATION.md)。

fxSDK 项目仍使用标准 CMake 和 fxconv 元数据，但发行包的 `fxsdk.exe`
仅提供原生路径/版本查询适配，并非上游完整命令行工具集；不包含 fxlink。
官方 SHC/fxlib 项目需要迁移编译选项、API 和资源配置，不能直接保证导入即用。

## 可选历史实现：WSL（以下并非默认部署流程）

入口：`wsl.exe -d FxSDK-Dev-20261114 -- /opt/fxide/bin/build-project SOURCE BUILD Debug|Release`。

SOURCE 和 BUILD 都是 Linux 绝对路径，可由 `wslpath -u` 转换 Windows 路径。SOURCE 需包含标准 fxSDK CMake 工程。BUILD 可放在工程内的独立子目录，也可以在工程外；不得等于 SOURCE 或包含 SOURCE。构建在 BUILD/.fxide-source 的暂存副本中进行，不修改 SOURCE。

默认选择唯一可执行目标；多目标工程可在根目录 `fxide.json` 中指定 `{"target":"myaddin","cmake":{"MY_OPTION":"ON"}}`。不得借该文件覆盖 IDE 管理的 CMake/工具链选项。用户工程及其构建脚本属于可执行的受信代码，IDE 不将任意 CMake 项目视为安全的纯数据文件。

Debug 使用编译及链接 launcher，在实际执行时过滤工程的 `-O*`、`-flto`、`-fomit-frame-pointer`、`-g0`、剥离符号选项。用户源文件编译追加 `-Og -g3 -fno-omit-frame-pointer -fno-lto`；最终链接使用 `-flto=auto`，让 GCC 14.1 的插件能处理现有 gint/fxlibc 库内仅有 LTO 的对象，用户对象本身仍然没有 LTO。因此现有工程即使固定了 `-Os`/LTO，也不会覆盖用户源文件的 Debug 配置。Release 保留原工程选项。静态 SDK 库不重新编译，库内保留优化，进入库函数时的源码定位、变量和逐行调试可能受限。

成功后输出 `BUILD/artifact.json`，schemaVersion 为 1，包含 elf、g1a、sourceDirectory、buildDirectory、sourceMappings、configuration、target、sha256 等字段。路径为绝对 Linux 路径。ELF 未剥离；G1A 是设备安装格式。`hardwareVerified:false` 表示本机构建/格式检查并不等于真机已通过。

每次开始先撤销旧 manifest；失败不会留下宣称成功的新 manifest。编译记录在 `compile_commands.json`。同一个 BUILD 目录只允许一个构建。取消入口：`/opt/fxide/bin/cancel-build BUILD`；它验证该目录记录的 PID、进程启动时间、命令行和独立进程组，再终止该组，避免仅关闭 Windows wsl.exe 后留下编译进程。

工具链固定在发行版内 `/root/.local`，构建服务固定在 `/opt/fxide/bin`。这些路径属于可移植 WSL rootfs 的内部布局，不要求用户 Windows 工程使用固定路径。

此稳定配置使用 GCC 14.1.0 / fxSDK 2.11.0 / gint 2.11.0。默认 libstdc++ 按无异常配置构建；C++ 编译显式追加 `-fno-exceptions`，遇到 `throw`/`catch` 会报错。普通 C++17 模板、RAII 和容器头可用，不提供 C++ 异常或线程支持。KhiCAS 的自定义异常运行库与 SJLJ 实验不被纳入稳定默认工具链。
