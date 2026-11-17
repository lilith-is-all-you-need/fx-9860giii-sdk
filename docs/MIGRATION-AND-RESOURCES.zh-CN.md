# 旧 fxlib 工程迁移与资源导入

2026-11-18 · 当前源码功能。原 0.2.0 发行 ZIP 不含本页的新工具；需要更新后的完整安装目录，或从源码构建。旧工程不会被就地修改。

## 先选择正确的兼容方式

| 输入 | 路径 |
| --- | --- |
| 旧 `.c` / `.h`，调用 fxlib API | 本页迁移工具 + `compat/fxlib` 公共兼容子集 |
| 已有 CMake + gint 源码 | 直接打开 CMakeLists.txt；资源工具也适用 |
| 只有 `.g1a` 二进制 | [Loader 套件](LOADER-SUITE.zh-CN.md)或模拟器；不能据此还原源码工程 |
| 官方 SHC `.lib`、专用汇编、直接寄存器或 syscall 跳板 | 需要单独移植；源码 wrapper 不提供 ABI 混链保证 |

`fxlibc` 是 C 运行库，不是 fxlib。模拟器的系统调用处理也不会给编译器提供 fxlib 源码接口。
公共兼容库采用独立实现，不分发专有 Casio SDK 头文件、库或历史游戏资源。

## 在 IDE 中使用

1. 选择“工具 → 迁移旧 fxlib 工程”，选原工程目录，再选新工程父目录和名称。
2. 工具将生成独立工程、CMake 配置、兼容库副本和迁移报告。阅读报告，再按 Ctrl+Shift+B 构建。
3. 选择“工具 → 导入资源”，选图片或二进制文件，指定格式和 C 符号名。单目标工程可以不填构建目标。
4. 导入后打开的 `project_assets.h` 提供可用声明。在源码中包含它，再构建与调试。

迁移报告的诊断是静态提示，不能发现所有宏展开、动态调用或运行时不兼容。
“生成成功”表示新工程已经建立，不表示所有旧源码已经编译或实机通过。
构建/调试期间以及加载已有只读编译产物时，资源导入不可用。
导入启动后，停止或关闭窗口会等待文件事务完成，避免只写入声明而没有更新资源清单。

## 命令行迁移

在 SDK 根目录运行；完整包自带 Python，首次运行无需联网安装：

```powershell
& ./sdk/native/host/python/python.exe ./tooling/legacy_project.py create --source C:/Projects/OldGame --output C:/Projects/NewGame --name NewGame --dry-run
& ./sdk/native/host/python/python.exe ./tooling/legacy_project.py create --source C:/Projects/OldGame --output C:/Projects/NewGame --name NewGame
```

也可用安装了 Pillow 的系统 Python。在源码仓库中，原生 Python 位于完整包的 `sdk/native/host/python/` 或本机 `dist-toolchain/native-sdk/host/python/`。
输出目录必须是新目录；不要选择原工程内部。工具复制源码，显式生成目标源清单，
并把兼容库放到新工程中，因此工程整体移动后不依赖仓库的绝对路径。

常见 `AddIn_main(int, unsigned short)` 入口通过适配文件接入 gint 的 `main()`。
旧启动段、SHC 专用指令和不支持的函数需要按报告处理；不要直接把专有 `fxlib.h`
复制回来覆盖公共接口。详细函数、返回值和语义边界以 [API 支持矩阵](../compat/fxlib/README.md) 为准。

手工接入现有工程时，复制 `compat/fxlib` 到工程内，再配置：

```cmake
add_subdirectory(compat/fxlib)
target_link_libraries(my_addin PRIVATE Fxlib::Compat)
# 仅在旧项目使用 AddIn_main 且没有 main 时添加：
target_sources(my_addin PRIVATE compat/fxlib/fxlib_entry.c)
```

自带 [legacy-fxlib 示例](../examples/legacy-fxlib)可以直接构建。
仓库主本和示例内副本由 `python tooling/sync_fxlib_compat.py --check` 检查，
修改公共库后先同步，避免不同模板带入不同实现。

## 资源格式与命令

| kind | 输入与输出 | 使用方式 |
| --- | --- | --- |
| `bitmap` | 图片 → 单色 C 字节数组，逐行补齐到整字节，高位在前 | 旧 `DISPGRAPH.GraphData.pBitmap`；宽高、stride、size 随头文件提供 |
| `image` | 图片 → fxconv 元数据和 gint `bopti_image_t` | `dimage(x, y, &symbol)` |
| `binary` | 原始文件 → C 字节数组 | `symbol` 与长度常量 |
| `font` | 已栅格化的字体图集 → fxconv 和 gint `font_t` | 指定网格和字符集，使用 gint 字体接口 |

```powershell
python tooling/project_assets.py import --project C:/Projects/NewGame --input C:/Art/player.png --kind bitmap --symbol player
python tooling/project_assets.py import --project C:/Projects/NewGame --input C:/Art/background.png --kind image --symbol background
python tooling/project_assets.py import --project C:/Projects/NewGame --input C:/Data/level.bin --kind binary --symbol level_data
python tooling/project_assets.py import --project C:/Projects/NewGame --input C:/Art/digits.png --kind font --symbol digits --font-grid 5x7 --font-charset numeric
python tooling/project_assets.py list --project C:/Projects/NewGame
```

可先添加 `--dry-run` 检查计划；多目标工程加 `--target my_addin`。
目标识别支持根文件、显式子目录及 `${PROJECT_NAME}`，忽略字面假分支；它不执行
CMake、不展开 `include`。动态条件、函数、宏、循环或未解析变量中的目标会明确拒绝，
这类工程应自行维护资源清单，或先提供确定的字面目标定义。
工具维护 `assets/fxstudio/` 中的受管理文件、声明头和构建片段；它保留用户已有的
CMake 内容，并在目标定义后接入。已有同名资源会校验内容，相同导入可重复执行，
冲突会报错。不要手工改写生成文件后期待工具覆盖；应使用新符号或先自行整理资源。

旧位图默认采用亮度 128 阈值，透明像素合成白色，行尾不足 8 像素时补白。
这是一种有损黑白转换，不是自动压缩。多帧图片、超大输入和无效符号应先处理后导入。
`font` 输入是位图字形表，不接受 TTF/OTF 自动栅格化。IDE 当前提供前三种格式，字体通过命令行导入。

```c
#include <fxlib.h>
#include <project_assets.h>

void draw_player(void)
{
    DISPGRAPH graph = {0};
    graph.x = 10;
    graph.y = 12;
    graph.GraphData.width = player_width;
    graph.GraphData.height = player_height;
    graph.GraphData.pBitmap = player;
    graph.WriteModify = 1;
    graph.WriteKind = 1;
    Bdisp_WriteGraph_DDVRAM(&graph);
}
```

fxconv 输出对象与上述原始位图数组结构不同，不能把 `bopti_image_t *` 强制转换为旧位图指针。
图片窗口仍然预览原图；最终转换效果需要编译运行后查看计算器屏幕。

## 兼容性与验证边界

公共库提供明确的源码兼容子集，未实现函数应在扫描/编译/链接阶段显露，或由已声明
接口返回明确错误。不要用成功返回值占位补齐不支持的行为。
当前公开清单含 57 个旧名接口；这不是完整 fxlib 覆盖率。5 个定时器为协作调度，
纯忙等循环需要调用 `fxlib_compat_poll()`；文字采用 ASCII 和替代字体。
文字、按键模式、定时器回调上下文、OS 菜单与文件系统存在设备相关语义，需参考支持矩阵。
即使编译和模拟器通过，仍要分别测试真机启动、绘图、输入、保存、MENU/EXIT 和再次进入。

本次验证记录见 [当前开发验证](VALIDATION-COMPAT-20261118.md)。历史 0.2.0 报告、
后续 Loader 实机反馈以及新兼容库测试是不同证据，不能合并为“全部实机通过”。

## English quick reference

The unreleased source tree adds a public fxlib-to-gint compatibility subset, a
portable legacy project generator, and managed resource import. In the IDE use
**Tools → Migrate fxlib project** and **Tools → Import resource**. Existing 0.2.0
archives do not contain these additions. The CLI commands above also work with
the SDK's bundled Python. Generated declarations are in `project_assets.h`.

Supported legacy calls can remain unchanged; SHC assembly, proprietary binary
libraries, direct system-call trampolines and unsupported APIs still require
porting. Consult the [API support matrix](../compat/fxlib/README.md). A successful
import is a generated project, not a successful build or device certification.
