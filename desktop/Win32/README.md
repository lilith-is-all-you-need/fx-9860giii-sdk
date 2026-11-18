# Fx Studio Win32

适用于 Windows x64 的 fx-9860GIII C / C++ 开发工作台。完整解压 ZIP，运行顶层的 `FxStudio.Win32.exe`。编译器、调试器、模拟器、Python 和 SDK 后台运行库均随包提供。桌面程序保存在电脑上，构建生成的 G1A 才复制到计算器。

## 第一次运行

1. 在欢迎页点击 **打开计数器示例**。工作台会在当前用户目录创建一份可编辑的 C++ 副本。需要 C 工程时，选择 **文件 → 新建工程**，模板选 C。
2. 工具栏选择 Debug 或 Release，点击 **构建**。输出窗显示编译日志、ELF、G1A 和字节数。**构建 → 打开产物目录** 可以定位文件。
3. 按 **F5** 开始源码调试，首次停在 `main`。再按 **F5** 运行，右侧显示计算器的真实 128 × 64 帧缓冲区。点击计算器上的 **+**，计数器增加。**放大屏幕** 显示整数倍实时画面，**保存 PNG** 导出原始分辨率。
4. 在 `change_counter` 内可执行行的左侧标记栏单击，或将光标置于该行后按 **F9**。继续运行并点击计算器的 **+**，即可检查局部变量和调用栈。
5. 停止调试，切换 Release 后再次构建。**文件 → 导出已校验 G1A** 会重新核对 ELF 和 G1A，然后写入所选位置。

安装目录含中文或单引号时，首次构建会把约 393 MB 的交叉工具链复制到本机构建缓存。进度显示在输出窗，后续构建会复用已校验的副本。工程目录可以使用中文。需要指定缓存时，可在工具链设置中选择英文路径。

## 操作入口

| 操作 | 入口 |
| --- | --- |
| 项目与源码 | 新建 C、C++ 或有界内存模板，打开 CMakeLists.txt、fxide.json 工程或已有 fxdebug.json 调试包。文件可拖入窗口，目录也可拖入。工程树双击打开文件，右键目录新建源文件。将新源码加入 CMakeLists.txt 后即可构建。 |
| 编辑 | 多文件标签、C/C++ 高亮、行号、断点边栏、撤销重做、查找和循环查找。Ctrl+S 保存，Ctrl+Shift+S 全部保存，Ctrl+W 关闭当前标签。保留文件原有换行和 UTF-8 BOM。 |
| 构建 | Ctrl+Shift+B 构建所选配置，可取消。诊断页双击文件位置跳转。工具链设置可指定 SDK、缓存、模拟器、GDB 和新工程的 WSL 发行版。原生工具链开箱可用。可选 WSL 构建沿用工程描述中的 backend 和发行版配置。 |
| 调试 | F5 启动或继续，Shift+F5 停止，F10 逐过程，F11 逐语句，Shift+F11 跳出。Ctrl+F10 运行到光标，Ctrl+Alt+F10 / F11 执行指令级单步。支持重启、条件断点、启停断点和读写数据断点。 |
| 检查状态 | 底部标签提供局部变量、监视表达式、栈帧、断点、寄存器、内存和反汇编。暂停时可展开变量成员、选择栈帧、修改变量和寄存器、读取或写入目标内存。监视和断点使用原版兼容的工程会话格式。 |
| 资源 | 双击工程树图片可看尺寸、透明背景、首帧和整数倍缩放。**工具 → 导入工程资源** 提供单色位图、gint 图片、二进制和位图字体，会同步生成 C 声明与构建规则。 |
| 旧工程 | **工具 → 迁移旧 fxlib 工程** 会在选择的位置生成新工程。API 支持范围见 `Studio/compat/fxlib/README.md`。 |
| Loader | **工具 → FX Profile Studio** 启动随包的独立工具，可批量准备 G1A/BIN、选择配套文件和单独导出 Loader。其界面、离线依赖和说明都在 `Studio/ProfileStudio`。 |
| 开发资料 | **帮助 → 计算器资料库** 可检索系统调用、主题和证据。用户指南、兼容手册、工程经验、Loader 说明与开发脚手架位于 `Studio/docs` 和 `Studio/scaffolds`。 |
| 自动化 | `Studio/FxStudio.Agent.exe --stdio`、`Studio/automation` 和 `Studio/skills` 提供原 SDK 的本地脚本与 MCP 接口。外部 Agent 拥有独立调试会话。 |
| 布局与语言 | 拖动工程树、检查器、计算器面板之间的分隔线。**工具 → Language / 语言** 可切换简体中文和 English。设置位于当前用户的 LocalAppData/FxStudioWin32。 |

桌面主界面使用 C++ 与 Win32 公共控件，编辑器使用 Scintilla / Lexilla。随包后台复用 FxStudio.Core 的构建、GDB 和模拟器逻辑。经典 IDE 位于 **工具 → 打开经典 IDE**。计算器端和系统调用的兼容范围以 SDK 文档及实机结果为准。

## Win32 源码与构建

新界面及后台源码位于包内 `Studio/sources/current/desktop/Win32`，同级源码树包含对应的 FxStudio.Core。编辑器依赖的固定版本和 SHA-256 在 `editor_deps.py`，相应离线输入在 `Studio/sources/current/editor-inputs`。在仓库中，构建需要 Visual Studio C++ x64、Windows SDK、CMake、Python 和 .NET 10 SDK。

从源码根目录执行下列 PowerShell 命令。解压包的源码根目录是 `Studio/sources/current`。在仓库中首次运行若缓存为空，会下载固定版本的编辑器依赖。

```powershell
python desktop/Win32/editor_deps.py editor-inputs
cmake -S desktop/Win32 -B build-win32 -A x64 "-DEDITOR_DEPS=$((Resolve-Path editor-inputs).Path)"
cmake --build build-win32 --config Release
dotnet publish desktop/Win32/host/FxStudio.Win32Host.csproj -c Release -r win-x64 --self-contained true -o C:/FxBuild/Win32Host
```

打整包时，`package.py base` 从有清单的完整 Loader Suite 创建独立输出，`package.py pack` 加入当前 SDK、编辑器依赖、新界面和对应源码并校验 ZIP。各参数见脚本的 `--help`。基础包原有的源码归档和历史验证仍位于 `Studio/sources` 与 `Studio/validation`。

## English quick start

Extract the entire archive and run **FxStudio.Win32.exe**. Use **Tools → Language / 语言 → English**. Open the counter example, press **Ctrl+Shift+B** to build and **F5** to stop at main. Press **F5** again, then click the calculator's **+** key. Export a verified Release G1A from the File menu. The SDK runtime and companion tools are bundled for offline use.
