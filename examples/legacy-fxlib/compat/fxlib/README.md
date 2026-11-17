# fxlib → gint 源码兼容子集

本目录是 Fx Studio 自行实现、MIT 授权的公共兼容层，不包含 Casio 的私有头文件或二进制库。
它让使用下面这些接口的旧 C 程序保留 `#include "fxlib.h"` 和 `AddIn_main()`。
**它不是完整 fxlib，也不保证任意 SHC 工程或已有 G1A 可以直接迁移。**

## 接入

完整、可搬移的示例在 `examples/legacy-fxlib`。复制该目录，在 Fx Studio 打开其中的
`CMakeLists.txt`，将旧源文件加入 `add_executable()` 的源文件列表。
独立工程应把本目录复制到工程内的 `compat/fxlib`：

```cmake
cmake_minimum_required(VERSION 3.15)
project(MyLegacy C)
include(GenerateG1A)
add_subdirectory(compat/fxlib)
add_executable(my_legacy src/old.c compat/fxlib/fxlib_entry.c)
target_link_libraries(my_legacy PRIVATE Fxlib::Compat)
target_compile_options(my_legacy PRIVATE -fsigned-char)
generate_g1a(TARGET my_legacy OUTPUT "MyLegacy.g1a" NAME "MyLegacy")
```

`fxlib_compat` 与 `Fxlib::Compat` 是同一个 CMake 目标，它传递 gint 链接与头文件目录。
`fxlib_entry.c` 提供 `main()`，先调用 `fxlib_compat_init()`，再调用 `AddIn_main(1,0)`。
已有自己的 `main()` 时不要加入入口文件；在自己的入口调用初始化函数。
标准旧源码尾部的 `InitializeSystem()` / `INIT_ADDIN_APPLICATION` 可以保留，但不会作为
gint 的启动入口。旧 `#pragma section` 会被 GCC 忽略；依赖其布局的自定义代码必须迁移。
C++ 源码包括本头文件后，`AddIn_main` 保持 C 链接。

移除旧工程中的官方 `fxlib.h/dispbios.h/keybios.h/filebios.h` 副本，避免同名文件优先遮蔽
本兼容层。**不要链接 SHC 的 `.lib`、旧启动对象或旧中断向量。** 需要第三方库时，用同一
GCC/ABI 重编译。`-fsigned-char` 是示例的明确选择，不会由兼容库强加给所有调用方。

## 支持矩阵

完整可扫描函数清单在 `api.json`；这里只概括边界。所有函数实际导出为 `fxlib_...`，旧名
在头文件中映射，避免覆盖 gint 内部的同名 OS 调用。`dispbios.h/keybios.h/filebios.h`
是转入这个头文件的简短兼容入口。

| 接口 | 实现与限制 |
| --- | --- |
| `Bdisp_AllClr_*`、`AreaClr_*`、`SetPoint_*` | DD（屏幕）和 VRAM 分离；带 DD 的调用立即刷新，VRAM 调用只改缓冲。坐标越界裁剪。|
| `Bdisp_PutDisp_DD`、`PutDispArea_DD`、`GetDisp_*` | 全屏 1024 字节、128×64、每行 16 字节、最高位为最左像素。区域两端包含。|
| `Bdisp_AreaReverseVRAM`、`DrawLineVRAM`、`ClearLineVRAM`、`GetPoint_VRAM` | 反色区域裁剪；线端点要求在屏幕内，越界线明确报参数错误。|
| `Bdisp_WriteGraph_*` | 原始单色位图、每行向上取整到字节；NORMAL/REVERSE 与 OVER/OR/AND/XOR 全部实现，裁剪后写入。其他模式报不支持。输入缓冲大小由调用方保证。|
| `Bdisp_ReadArea_*`、`GetVRAMAddress` | 读取区域需在屏幕内；调用方提供至少 `ceil(width/8)*height` 字节，不能与来源重叠。VRAM 指针只在 gint 环境使用。|
| `locate`、`Print/PrintRev/PrintC/PrintRevC/PrintLine/PrintRLine/PrintXY` | ASCII 32–126，普通字格 6×8；locate 从 (1,1) 到 (21,8)，不自动换行。使用 gint 的开放字体，不保证 Casio 字形逐像素相同。|
| `PrintMini` | 4×6 字格，由开放 5×7 字形采样得到 3×5 图形；四个 MINI 模式有效。它不是官方小字体，精确排版需验收。|
| `GetKey`、`GetKeyWait` | 返回旧 OS 逻辑键码（例如 EXE=30004），支持 SHIFT/ALPHA 单次修饰、方向键连发、MENU 与 SHIFT+AC 关机。没有 OS 的修饰锁定、菜单式数学输入或背光快捷键完整模型。未列出的修饰组合保留基础键码。|
| `IsKeyDown/IsKeyUp` | 仅接受未加 SHIFT/ALPHA 的基础旧逻辑键码，如 `KEY_CHAR_0`、`KEY_CTRL_EXE`；可同时检测多个物理按键。同步 gint 事件，保留按下事件供后续 GetKey/Bkey 使用。不能传入 `KEY_CHAR_A` 等修饰结果、gint 物理码或自定义 `KeyDown` 的十进制矩阵码。未映射的键码返回负错误，不能把非零一概当作按下。|
| `Bkey_GetKeyWait` | 0 阻塞 / 1 轮询 / 2 超时；超时单位**秒**（0–3600）；输出旧列/行坐标，如 0→(7,2)、AC→(1,1)。menu=0 且非轮询时回系统菜单，其他情况返回 MENU 坐标。`unused` 置零，不支持 OS 注入的逻辑键码。|
| `Bkey_*RepeatTime*` | 独立重复配置，参数单位 25ms；实际精度受 128Hz 时钟量化。默认约 500/125ms。GetKey 仅重复方向键，Bkey 重复最后按住的键。|
| `Sleep`、`RTC_GetTicks`、`RTC_Elapsed_ms` | 128Hz RTC，午夜归零；短时间差处理午夜回绕，最长小于一天，非单调的系统时间修改不在保证内。Sleep 同时分派协作定时器。|
| `SetTimer/KillTimer` | 5 槽 ID=1..5；毫秒参数向上取整到 128Hz，正间隔且小于一天。支持替换、自取消和多槽；成功返回0，错误负值。**协作调度，非硬件中断兼容**，详见下文。|
| `Bfile_OpenFile/CloseFile/ReadFile/WriteFile/SeekFile/GetFileSize/CreateFile/DeleteFile/CreateDirectory/DeleteDirectory` | gint 的 `gint_world_switch` 内调用 BFile；仅 GIII/Fugue 文件系统，其他文件系统报不支持。保留本机 BFile 返回值，包括负错误；seek 是绝对位置，read 的 position=-1 使用当前偏移。|
| `Bfile_StrToName_ncpy/NameToStr_ncpy` | ASCII 路径与16位 FONTCHARACTER 转换，按给定长度填充；长度不足时不自动添加额外终止符。非 ASCII 报不支持。|

未实现的函数不会提供“返回成功”的空桩。典型缺项：`SaveDisp/RestoreDisp/PopUpWin`、
MCS/主存储对象、文件搜索与剩余容量、串口/USB、剪贴板、设置、`SetQuitHandler`、任意 syscall
机器码跳板、旧汇编/SH3 硬件寄存器访问。编译/链接失败或者迁移扫描的未支持列表应先处理。

## 运行约束和可观察错误

`GetKey`/`GetKeyWait`/`Bkey_GetKeyWait` 的等待循环、`IsKeyDown/IsKeyUp`、`Sleep`、
`Bdisp_PutDisp_DD/PutDispArea_DD` 自动调用 `fxlib_compat_poll()`。纯计算循环需主动调用它。
离开主线程的 OS world switch 或 MENU 期间不会分派协作回调；回到程序后合并错过的到期，
不会突发执行全部历史周期。回调执行期间不递归分派其他定时器，因此长回调（包括回调中等待
按键/睡眠）会推迟其他槽。不能依靠这里的定时器唤醒不调用这些函数的忙等循环。需要精确
中断时序的项目应直接迁移到 gint `timer_*`，不能宣称零改动。

所有函数共用粘性的 `fxlib_compat_last_error()` 和 `fxlib_compat_last_function()`；用
`fxlib_compat_clear_error()` 显式清除。`fxlib_compat_set_error_handler()` 可安装错误处理器，
包含原来没有返回值的绘图/文本接口。处理器不得递归调用失败的接口。参数错误为 -1000，
不支持为 -1001，32 项按下队列溢出为 -1002。溢出时保留已有按键、丢弃新按下事件，报告错误。
有返回值的函数同时返回错误；未支持字符绘成 `?` 并留下错误，不冒充原字符已正确显示。

DD 读取来自本层的屏幕镜像；如果混用原生 `dupdate()`，需先调用 `Bdisp_PutDisp_DD()`
同步镜像。不要同时启用 gint 灰度引擎，或在中断中使用这些函数。兼容层常驻显示/字体
缓冲约2 KiB，另有按键、定时器和状态；不包含调用方资源、gint自身内存及栈。

文件读写保留 GIII 原生 BFile 语义，不是 POSIX：固定初始文件长度、越过 EOF 的返回值/
填充行为由设备 OS 决定；调用方应先查文件大小，不可只据返回长度推断实际文件内容。
旧 C 中的原始位图数组可直接继续使用；fxconv 的 `bopti_image_t` 不能直接强转为
`GRAPHDATA.pBitmap`。PNG 需使用匹配转换器生成原始单色数组，或改用 gint 图像接口。

## 维护与验证

仓库主本是 `compat/fxlib`。运行 `python tooling/sync_fxlib_compat.py` 更新自包含示例，
`--check` 检查差异；该工具不会删除意外出现的文件。主机语义回归：
`python -m unittest discover -s tests -p test_fxlib_compat.py`。
它使用真实 `fxlib.c` 配合确定性硬件替身，覆盖 DD/VRAM、4种位图组合、裁剪/拒绝、文本、
键码与超时/菜单、跨午夜/多定时器/防重入、文件参数与错误。缺 C 编译器会明确跳过执行测试。
后端测试另外执行真实 `fxlib_gint.c`，验证每种文件操作均经过 world-switch 边界，以及显示/
字体状态恢复。主机测试不验证 GIII 驱动、OS 文件保存或实体按键时序；目标编译和模拟/实机
验证须单独记录。

接口依据是本地公开 gint 2.11 头文件（display/keyboard/rtc/bfile/gint）及公开 API 说明：
[Casio SDK 键盘公告](https://edu.casio.ru/download/fx-9860G_SDK_Announcement.pdf)、
[Simon Lothar 键盘研究](https://media.taricorp.net/prizm/simon_chm/fx_legacy_keyboard.htm)、
[定时器研究](https://media.taricorp.net/prizm/simon_chm/fx_legacy_timer.htm)。
只使用互操作所需的接口事实，代码和说明均重新编写；未复制官方 SDK 头文件或外部 KhiCAS 代码。

## English summary

This MIT source compatibility subset supplies independently implemented legacy function names on top of
gint. Link `Fxlib::Compat` and optionally compile `fxlib_entry.c` to keep `AddIn_main()`. Keep the compat
directory inside the project for portable native builds. It supports monochrome display/bitmap operations,
ASCII text, legacy logical and matrix keys, five cooperative timers and world-switched GIII/Fugue file I/O.
It is not a complete fxlib implementation, a binary converter, or a drop-in SHC runtime. Fonts, modifiers,
timer scheduling, filesystems and unknown APIs have the explicit limits above. Sticky diagnostics and
negative errors expose rejected operations. Host tests do not certify physical hardware behavior.
