# 工程经验与可复制脚手架

仅在新建有内存约束的应用、处理失败恢复、比较源码副本或准备实机验收时读取。
普通计数器调试继续使用现有流程，不必运行全部检查。

## 可直接运行

使用 Python 3.10+ 或包内 Python，脚本为本 skill 的 scripts/engineering.py。
它不启动 Agent、编译、下载或操作硬件。参数中的路径均可带空格、中文、撇号。
运行结果是 JSON；0 为所请求检查成功，2 为差异/超预算，1 为输入/运行错误。

~~~powershell
$engineering = Join-Path $skill 'scripts\engineering.py'
& $python $engineering new guarded-c 'C:\FxProjects\guarded'
& $python $engineering new evidence-session 'C:\FxProjects\evidence'
& $python $engineering snapshot 'C:\FxProjects\guarded' --output 'C:\FxProjects\evidence\source.json'
& $python $engineering compare 'C:\FxProjects\guarded' --snapshot 'C:\FxProjects\evidence\source.json'
~~~

目标目录和 JSON 输出必须是新路径。snapshot 按内容哈希记录源码/配置/资源，
排除 .fxstudio、bridge.json、.git、build*、编译二进制和常见凭据；不是环境备份。
compare 只报告新增/删除/修改，不回滚。不要用当前目录名称猜源码或产物身份。

guarded-c 使用固定512 B字节临时区、显式错误码和成功后提交；不复制 Giac。
按普通 SDK 流程构建。调试停在 demo_ready 时画面已绘制，
selftest_failures 应为0。EXE成功，F1第二次临时申请失败，F2注入取消；
失败/取消后 app 不变、scratch.used归零，再次EXE能成功。
F2是取消路径测试，不是计算中键盘轮询。详细内存合同在模板 README。

## 预算与实机证据

从 build.run 的实际返回结果取得 G1A 路径，再执行：

~~~powershell
& $python $engineering budget $g1a --policy 'C:\FxProjects\guarded\budget.json' --output 'C:\FxProjects\evidence\budget.json'
& $python $engineering hardware-record $g1a --output 'C:\FxProjects\evidence\hardware.json'
~~~

budget 只核字节和哈希，不能替代 SDK 的完整 ELF/G1A 校验，也不能证明能安装。
政策文件中的 basis 要注明依据。现有 SDK 采用2,000,000 B暂定门槛；
其他项目的2,094,444 B实机样本不能自动改成统一OS上限。
512 B scratch和额外16 KiB文件余量都是模板选择，不是设备极限。

hardware-record 所有结果初始not_run，必须从真实设备观察填入。
前置条件失败导致后续未执行时用skip；有限重复成功不能写成长期无泄漏。
模拟器不能验证物理代码缓存、完整菜单和EXIT直接重入。

## 来自旧项目的关键约束

1. v21这类项目批次不是Giac2.1；目录名、版本字段和文件名不替代输入哈希。
2. uSTL/std、对象大小、大小端、异常运行库、new/delete和启动代码须成套匹配。
   当前SDK不支持C++异常/线程；不要复制旧CAS全局分配器或unwinder。
3. 临时空间rewind后指针失效；它不是任意对象图回滚或析构。
4. 函数/对象名义大小不等于删去后的净节省；完整映像要包括RAM初始化数据和文件头。
5. 文件读取不等于可执行映射；旧LIB缓存同步实验不是通用加载器。
6. 只在自己的state/输出目录执行生命周期操作；不要修改原工程或覆盖已验证发布包。

skill 的 assets/scaffolds 为同步生成副本；本仓库维护源在 scaffolds/，
发布时验证 scaffolds-manifest.json。完整63案例和迁移依据在SDK的
docs/engineering；独立skill包携带本条件说明与模板，不携带整个历史工程。
