# 超限 Loader 源码示例（fx-9860GIII）

[English](README.en.md) · [FxStudio 普通加载手册](../../../docs/LOADER-SUITE.zh-CN.md)

这个例子回答一个具体问题：程序作者能否在有源码时，让自己的测试程序读取普通 2 MiB 窗口以外的一页，然后退出？例子含一个计算器启动器 ExtLoad 和一个与它配对的最小程序。两者独立编译。普通 FxStudio 的「为 Loader 准备 G1A」上限为 2,097,152 字节，含文件头。

## 从源码跑一次

1. 把本示例复制到可写目录。在完整 FxStudio Windows SDK 中依次打开 `probes/extended-cas` 和 `probes/source-guest`，各构建一次 Release。前者构建 ExtLoad，后者构建测试程序。构建记录给出各自的 G1A 路径。下面使用这两个工程内的标准输出路径。
2. 从示例根目录运行以下 PowerShell 命令。使用 Python 3，从新建的输出目录开始。测试数据和页表描述在电脑端生成。

~~~powershell
$guest = "./probes/source-guest/.fxstudio/build/Release/artifacts/addin.g1a"
$loader = "./probes/extended-cas/.fxstudio/build/Release/artifacts/addin.g1a"
python tests/make_source_guest.py $guest ./out/FXAPPS/DEMO513 --bytes 2097156
Copy-Item $loader ./out/ExtLoad.g1a
~~~

3. 将 `out` 的内容复制到计算器存储根目录。应看到 `ExtLoad.g1a`、`FXAPPS/DEMO513/IMAGE.BIN` 和 `FXAPPS/DEMO513/EXT.PRF`。在系统菜单启动 ExtLoad，选中 DEMO513 后按 EXE。该目录用目录名作标题，示例可省略图标和 APP.MET。
4. 测试程序读取每一页的首个字，并检查第 513 页的标记。它没有游戏或计算界面。正常返回会进入会话关闭流程，可经系统菜单选回启动器。失败时记录屏幕上的 Error、Stage、Status（如有）。这个测试只覆盖示例自己的读取和退出路径。

## 从问题定位源码

| 要找什么 | 文件与约定 |
| --- | --- |
| 程序如何接入？ | [测试程序 main.c](probes/source-guest/main.c) 调用 `fxlarge_bind(api)`。返回 1 才能使用 `FxLargeApi`。测试结束后调用 `fxlarge_unbind()`，成功返回 1。两者失败均返回 0。 |
| 库在哪？ | [runtime.h](probes/source-guest/vendor/fxlarge/include/fxlarge/runtime.h) 定义 ABI v1。[CMakeLists.txt](probes/source-guest/CMakeLists.txt) 从项目自己的 vendor 目录引入 `FxStudio::LargeRuntime`。其他项目要显式引入这份源码。 |
| 启动器怎么找到程序？ | [启动器 main.c](probes/extended-cas/src/main.c) 使用同目录的 `EXT.PRF` 与 `IMAGE.BIN`，核对镜像长度和摘要，在计算器上查询页地址。 |
| 页数、容量和错误在哪定义？ | [ext_profile.py](tooling/ext_profile.py) 中的 `encode_profile` 和 `decode_profile`，以及 [profile.h](probes/extended-cas/vendor/fxlarge/include/fxlarge/profile.h)。`pageCount` 为文件大小除以 4096 后向上取整，默认 `pageCapacity` 再向上补到 16 的倍数。本例分别是 513 和 528。 |
| 能放多大？ | 当前示例容量最多 768 页。电脑端的存储预算为 3,000,000 字节，需扣除描述文件开销及默认 8192 字节余量。实机还检查空闲存储和 RAM。容量字段不能增加可用空间。 |

`make_source_guest.py` 专为这个小测试程序填充页标记，要求其代码放在第一页、尾页至少能读四个字节。移植自己的程序时，请从源代码、初始化和退出生命周期入手。简单改后缀或给现有二进制加文件头不能证明它遵守相同的 ABI。真实程序的定时器、回调、存档以及 MENU 选回需要各自的验收记录。

2026-11-19 本地验证：两个项目的 Debug 和 Release 均编译通过。使用 Release 产物运行固件辅助模拟器，观察到一次窗口外补页，测试程序返回 0，启动器释放分配的内存。这一版仍待实机验收。
