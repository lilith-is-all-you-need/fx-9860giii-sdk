# Guarded C：失败后仍可重试的起步工程

适用于当前 Fx Studio/gint 的 C11 工程。依赖完整 SDK，不嵌入 CAS、Python、
C++ 异常、全局分配器替换或动态加载器。512 字节是此示例的静态临时区选择，
不是测得的设备 RAM 上限。

## 使用

用 Fx Studio 打开本目录，先编译 Debug，再调试。在 demo_ready 设置断点，继续执行
后屏幕应显示 Tests:OK；全局 selftest_failures 应为 0，scratch.used 应为 0。
这里是明确的绘制后断点；停在 main 时尚未画屏属于正常现象。

| 操作 | 预期状态 |
| --- | --- |
| EXE | Value 变为 120，Runs 加一，Status:OK |
| F1 | 在第二次申请临时内存时人为失败，Status:NO MEMORY；Value/Runs 不变 |
| F2 | 在循环中合作式取消，Status:CANCELLED；Value/Runs 不变 |
| 失败或取消后再次 EXE | 能正常成功；临时占用归零 |
| EXIT 后直接重入 | 初始化重新开始；实机必须另测 |

示例 F2 在进入运算前选择取消注入点，用于演示失败路径，**不是长运算期间实时扫描键盘**。
把模型用于长任务时，应在循环中接入自己的键盘/取消回调。
旧发行模拟器中启用 gint_setrestart(1) 后 EXIT 可能立即重新开始；当前源码已有有限的
菜单等待/恢复/替换模型，仍不是完整 OS 生命周期；
终止电脑调试请用停止按钮，不能把这种行为填为实机菜单测试通过。

## 文件职责

- src/fx_arena.*：单调临时分配区，按字节容量、对齐和高水位计量；支持按次注入失败。
- src/model.*：申请两个临时区，计算成功后才提交持久模型，所有出口回退到入口 mark。
- src/contract.c：对齐、越界大请求、无效参数、第一次/第二次申请失败、
  50 次取消、50 次成功、容量不足和保护字节检查。
- src/main.c：gint 绘制与事件循环，明确重启初始化；不在绘图接口里执行业务。
- tests/host_main.c：同一组内存/模型断言的宿主入口，不需要 gint。
- budget.json：带依据的工程预算示例；保持当前 SDK 的 2,000,000 B 上限策略并预留
  16 KiB。这两个数字都不是新测定的系统极限，也不会改变 SDK 自身的校验器。

## 本地 C 检查

在本目录，用已有宿主 GCC 执行；不要使用 sh-elf-gcc 生成 Windows 可执行文件：

~~~powershell
gcc -std=c11 -O2 -Wall -Wextra -Werror src/fx_arena.c src/model.c src/contract.c tests/host_main.c -o host-contract.exe
.\host-contract.exe
~~~

退出码 0 表示这组宿主断言通过。仓库中也可运行 python tooling/test_guarded_host.py。
宿主指针宽度、对齐和执行平台与 SuperH 不同，所以仍应做目标 Debug/Release 构建与
模拟器回放。实际安装前再检查屏幕、按键、失败恢复和 EXIT→直接重入。

## 内存合同

arena 只处理短期 scratch，不提供单块 free、压缩、分页或可持久化对象。
mark 及其后的所有指针在 rewind 后失效；不要保存到模型、全局表或 UI 中。
rewind 不清除内容，peak 和 attempts 是诊断历史，不等于当前使用量。
fx_arena_fail_at 重置申请计数，0 关闭注入；合法非零申请按次计数。
初始化时传入真实、存活的缓冲区及真实长度，不能伪造容量；arena 不支持并发共享。

用字节缓冲与 memcpy 储存示例临时数据，避免把 char 数组强转为不同对象后的别名/
生命周期问题。未来容纳 C++ 对象时，必须另外处理构造和析构；rewind 不是析构。

链接 map 与 .su 文件用于观察成本；单函数 .su 不是完整调用链和中断栈峰值。
预算工具只核文件字节及身份，完整 ELF/G1A 内容配对继续由 SDK 原校验器承担。
