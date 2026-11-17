# 库、工具链与脚手架操作手册

## 依赖分工

| 组件 | 在本 SDK 中做什么 | 常见误用 |
| --- | --- | --- |
| Windows Python | 执行构建、工程记录及 skill helper | 不意味着目标 G1A 内嵌 Python |
| CMake + fxSDK/fxgxa/fxconv | 配置目标、封装 G1A、转换图片等资源 | CMake 编译成功不等于设备识别；转换产物需入实际目标 |
| GCC14.1 / binutils2.42 | Windows 上产生 big-endian SuperH 指令 | sh-elf 文件名与 sh3eb target triplet不能仅按名字判缺失 |
| gint2.11 | 屏幕、按键、启动、OS world 与驱动 | 模拟器 OS 行为不完整，真实退出菜单必须实机测 |
| fxlibc / OpenLibm / libgcc | C 运行库、数学及编译器辅助 | 旧 libfx.a 不与这些库等价；ABI/soft-float必须匹配 |
| libstdc++ | 示例中的 C++17 string/vector 和正常 RAII | -nostdlib 时显式链接 stdc++；不保证异常或 OOM 恢复 |
| GDB16.3 + SuperH 模拟器 | 执行目标指令并断点、查看状态与屏幕 | 不是周期精确、物理缓存、完整 Casio OS 或真机调试 |
| FxStudio.Agent + skill helper | 已有异步操作/调试连接与生命周期 | 不另造第二套领域协议；discover 后按 schema 调用 |

以上是当前项目的固定版本记录，精确输入、目标运行库哈希和 native LTO 限制见
[原生 SDK](../../tooling/native-sdk/README.md)，许可及对应源码见
[source-notices](../../source-notices/README.md)。新增工程工具只依赖 Python 标准库，
没有引入网络服务、第三方 Python 包、计算器端 Python 或新的 CAS。

## 创建新工程

仓库根目录执行以下命令；如果使用独立 skill，脚本改为
<skill>/scripts/engineering.py。Python 可用完整包 sdk/native/host/python/python.exe。

~~~powershell
python tooling/engineering.py new guarded-c C:\FxProjects\guarded
python tooling/engineering.py new evidence-session C:\FxProjects\guarded-evidence
~~~

模板固定从随 skill 携带的 assets/scaffolds 读取，不依赖旧 KhiCAS 路径。
目标目录必须不存在；没有 --force，没有覆盖合并。源码维护位置是仓库 scaffolds，
skill assets 是由同步脚本生成并校验的副本。

guarded-c 的 README 给出按键和内存合同。用 IDE 或原 skill 打开新目录，
按 Debug→绘制后断点 demo_ready→按键回放→Release 的已有流程使用。
示例通过普通 gint/CMake 编译，不需要特殊系统权限或重新安装工具链。

## 冻结源码与比较副本

~~~powershell
python tooling/engineering.py snapshot C:\FxProjects\guarded --output C:\FxProjects\guarded-evidence\source.json
python tooling/engineering.py compare C:\FxProjects\guarded --snapshot C:\FxProjects\guarded-evidence\source.json
~~~

记录相对路径、字节和 SHA256，不依赖文件时间或同名目录。
源码、配置、文档和 PNG/SVG 被记录；构建目录、.git、.fxstudio、bridge.json、
.env、常见私钥名和二进制产物被排除。它不是完整备份，也不证明依赖版本。
需要保存整个环境时另外保留固定第三方源码、工具链 manifest 和合法可分发材料。

新增、删除、同长度修改都分别报告；compare 不恢复文件、不执行源码、不跟随目录
符号链接。空集合和不支持的清单拒绝成功。目录别名、单文件超过64 MiB或额外数据格式
需先明确输入范围，不能悄悄换快照规则后继续与旧结果比较。

输出 JSON 路径必须不存在。推荐放在单独证据目录，或工程的 .fxstudio/evidence 下，
防止其他报告成为下一次源码快照的新增输入。独立 SDK/VM 副本比较时保留相对目录结构。

## 产物预算与完整性

~~~powershell
python tooling/engineering.py budget C:\FxProjects\guarded\build\guarded.g1a --policy C:\FxProjects\guarded\budget.json --output C:\FxProjects\guarded-evidence\budget.json
python tooling/engineering.py hardware-record C:\FxProjects\guarded\build\guarded.g1a --output C:\FxProjects\guarded-evidence\hardware.json
~~~

上面的 build 路径是说明示例；实际路径以 build.run 返回的 g1APath 为准。
budget 使用完整文件长度，usableBudgetBytes = maxG1aBytes - reserveBytes。
必须写明 kind:project-policy 和 basis，不能将猜测的系统上限当实测值。
报告同时记录产物哈希、余量和 not_tested 的硬件状态。

**预算工具不验证 G1A 头、ELF 装载段或内容配对。** 即使对一个无效但足够小的
.g1a 文件返回预算通过，它仍不能安装。完整校验由现有 BuildService /
ArtifactPairVerifier 执行；已有 Python 构建入口也做逐段验证。
不要增加一份同名但更弱的“发布通过”结论。

hardware-record 只生成空白手工观察单并绑定文件身份，不会连接或操作计算器。
本模板按 not_run/pass/fail/skip 分类，没有默认成功或自动填实机测试次数。

## 返回值与副作用

| 命令 | 写入 | 退出码 |
| --- | --- | --- |
| new | 创建全新工程或记录模板目录 | 0成功；1拒绝/输入错误 |
| snapshot | 全新快照 JSON | 0成功；1输入/输出错误 |
| compare | 无写入 | 0一致；2有差异；1输入错误 |
| budget | 仅指定 --output 时创建新 JSON | 0符合预算；2超预算；1参数/输出错误 |
| hardware-record | 新建未测试记录 | 0成功；1输入/输出错误 |

所有参数通过普通 argv 传递；空格、中文和撇号路径用 PowerShell 单独引号包裹，
复杂操作参数仍按原 skill 使用 JSON 文件。不要拼接 shell 命令或重用系统 HOME 变量。

## 维护与验证

~~~powershell
python tooling/sync_engineering_skill.py
python tooling/sync_engineering_skill.py --check
python -m unittest discover -s tests -p test_engineering.py
python tooling/test_guarded_host.py --cc gcc
python tooling/test_guarded_target.py --package C:\FxStudio --output C:\FxTests\guarded-new-run
~~~

同步器只管理 skill 的模板副本；出现额外文件时拒绝自动删除。发布 skill 前必须
通过 --check。目标代码有变化后再跑真实 SDK Debug/Release 和模拟器检查，
不能靠宿主 C 测试代替 SuperH 执行。

目标 runner 使用现有 helper/Agent 协议，在全新输出目录复制模板并保存七个场景的
屏幕和变量结果，最后关闭它自己创建的会话与后台进程。输出目录已存在时直接拒绝。
没有完整本机 SDK 时不要伪造结果，也不要因此自动下载/重建编译器。

tooling/package_skill.py 会包含工程工具、条件阅读说明、模板及来源清单。
完整包 assembly 与 corresponding-source 收集器也已加入 scaffolds；
本次不覆写或重发既有经过验证的 0.2.0 运行时包。
