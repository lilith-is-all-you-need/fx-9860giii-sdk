# Legacy fxlib example

复制整个目录即可在 Fx Studio 打开 `CMakeLists.txt`，源码保留 `fxlib.h` 和 `AddIn_main`。
EXE 增加计数，EXIT 返回；定时器在 GetKey 等待期间继续协作分派，下一次按键后显示最新计数。
原始单色十字位图直接由旧 `DISPGRAPH` 接口绘制。

将自己的旧 `.c` 加入 CMake 源列表，并移除示例 `src/main.c`，避免多个 AddIn_main。
本目录的 `compat/fxlib` 是公共兼容子集的同步副本，因此不依赖仓库外部路径。
支持范围、错误处理、字体/定时器/文件系统差异见 [兼容层说明](compat/fxlib/README.md)。

This portable example intentionally uses only legacy API names. Copy the whole project, replace the
example source and update the CMake source list. The compatibility layer is a documented subset; see
its support matrix before treating an old program as a zero-edit migration.
