# 用 skill 接入 Fx Studio

适用于 Windows x64 和完整的 Fx Studio 离线包。无需在 AI 客户端注册 MCP，
也无需打开 IDE；AI 必须已有本地文件读写和运行程序的能力。安装说明无法赋予
一个纯网页聊天环境访问电脑的权限。

## 安装与准备

1. 下载并解压完整离线 SDK。0.2.0 请使用修正启动问题的 **v0.2.0-r1** 发布包。
2. 将发行附件 `FxStudio-skill-1.0.0.zip` 中的 `fxstudio` 文件夹放进客户端支持的
   skills 目录。Codex 可使用 `%USERPROFILE%\.codex\skills\fxstudio`。
   源码仓库中的相同内容位于 `skills/fxstudio`；未来整合包也使用这个路径。
3. 让客户端重新发现技能，调用 `$fxstudio`，并告知 SDK 解压目录和工程目录。
   不同客户端的技能目录与刷新方式可能不同。

建议首先让 AI 做：“使用 fxstudio，复制计数器示例，编译并验证按加号后计数增加，
给我运行截图和生成的 G1A。”现有工程则明确它的目录。

下面的 PowerShell 示例也可以独立验证接入。将前两个路径替换为实际路径；
`$state` 为当前任务独享目录，不要与另一位 agent 共用。

```powershell
$package = 'C:\FxStudio'
$skill = Join-Path $env:USERPROFILE '.codex\skills\fxstudio'
$python = Join-Path $package 'sdk\native\host\python\python.exe'
$helper = Join-Path $skill 'scripts\fxstudio.py'
$state = 'C:\FxProjects\counter\.fxstudio\skill\task-1'
& $python $helper --package $package --state $state doctor
& $python $helper --package $package --state $state start
& $python $helper --state $state discover session.open
```

`doctor` 只检查必要文件，输出 `package`、`python`、`filesChecked`；不声称验证
整个 SDK。`start` 成功后返回 `hostId` 和 `agentRunning: true`。整个 SDK 的哈希与
桌面组件检查使用发行包中的 `Verify-Package.ps1`。

## 完整调用流程

先将包内 `examples/counter-cpp` 复制到自己的工程目录，排除 `.fxstudio`、
`build*` 和 `project.fxide.json`。为避免 Windows 命令行的 JSON 引号问题，
将参数写入 UTF-8 文件（带 BOM 也支持）。不要直接修改发行包里的模板。

```powershell
$project = 'C:\FxProjects\counter'
$argumentFile = Join-Path $state 'arguments.json'
@{ projectPath = $project } | ConvertTo-Json | Set-Content -Encoding UTF8 $argumentFile
$reply = & $python $helper --state $state call session.open --args-file $argumentFile | ConvertFrom-Json
$operation = $reply.structuredContent.operation
while ($operation.status -in @('queued', 'running')) {
    $reply = & $python $helper --state $state operation $operation.operationId | ConvertFrom-Json
    $operation = $reply.structuredContent.operation
}
if ($operation.status -ne 'succeeded') { throw ($operation.error | ConvertTo-Json) }
$session = $operation.result.sessionId
```

所有后续 `call` 都采用上述轮询规则。工具返回一个 operation 不等于操作完成；
只有 `status: succeeded` 才可继续依赖它的下一步。失败详情在 `operation.error`，
提交被拒绝的错误在 `structuredContent.error`。CLI 遇到这些错误返回退出码 2，
本地路径/通信错误返回 1，正常返回 0。

| 顺序 | `call` 后的命令 | JSON 参数 |
| --- | --- | --- |
| 1 | `build.run` | `{"sessionId":"上一步ID","configuration":"Debug"}` |
| 2 | `debug.launch` | `{"sessionId":"上一步ID","stopAt":"main.cpp:49"}` |
| 3 | `debug.snapshot` | `{"sessionId":"上一步ID","include":["screen","locals","stack"]}` |
| 4 | `debug.resume` | `{"sessionId":"上一步ID"}` |
| 5 | `debug.key` | `{"sessionId":"上一步ID","key":"PLUS","action":"press"}` |
| 6 | `debug.pause` | `{"sessionId":"上一步ID"}` |
| 7 | `debug.snapshot` | `{"sessionId":"上一步ID","include":["screen"],"expressions":["counter.value"]}` |
| 8 | `debug.stop` | `{"sessionId":"上一步ID"}` |
| 9 | `build.run` | `{"sessionId":"上一步ID","configuration":"Release"}` |
| 10 | `session.close` | `{"sessionId":"上一步ID"}` |

`main.cpp:49` 是随包 C++ 计数器示例绘制后的位置；修改源码后应使用实际行号。
不指定 `stopAt` 时默认停在 `main`，此时屏幕可能尚未绘制。

将每行参数写进同一个参数文件后，使用：

```powershell
& $python $helper --state $state call build.run --args-file $argumentFile
# 替换为返回的 operationId，重复查询直至终态
& $python $helper --state $state operation '返回的operationId'
# 对已完成的 debug.snapshot 操作导出屏幕；截图在本机生成
& $python $helper --state $state operation '截图operationId' --screen 'C:\FxProjects\counter\screen.png'
& $python $helper --state $state events --after 0 --session $session
& $python $helper --state $state stop
```

编译结果中的 `g1APath`/`elfPath` 指向实际产物（以发现接口和返回 JSON 为准）。
让 AI 用其图片查看工具读取输出 PNG；终端不会打印整幅图像的 base64。
常用按键为 `PLUS`、`MINUS`、`LEFT`、`RIGHT`、`UP`、`DOWN`、`EXE`、`EXIT`、
`F1` 至 `F6`、`0` 至 `9`。发送按键时目标必须正在运行。

## 多轮会话和并发

- 每次 CLI 调用连接同一 `--state` 的后台进程。因此切换终端命令后，断点、变量、
  sessionId 和 operationId 仍然存在。默认两小时无调用后自动清理；`--idle-seconds`
  可在首次启动时调整，最小 30 秒。长时间不轮询会触发此超时。
- 每个任务用自己的 state 目录。不同任务同时编译时，还需要独立工程副本或
  独立构建目录；后台隔离不会绕过 SDK 的同构建目录互斥。
- 同一 state 的并发启动由系统文件锁协调，不会产生两个有效 host。已运行的 host
  不能悄悄换 SDK 路径。只对自己任务的 state 调用 `stop`。
- helper 在 `127.0.0.1` 随机端口接受带随机令牌的本机请求，不对外监听。
  `bridge.json` 含凭证，保存在 `.fxstudio` 内，不应提交、上传或展示给他人。
- 正常结束用 `session.close` 和 `stop`。若客户端中断，仍可用相同 state 继续。
  若 host 本身崩溃，旧会话与请求去重记录不能恢复；重新打开工程和构建。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 找不到 SDK | `--package` 指向包含 `FxStudio.Agent.exe` 的完整发行包根目录，不是仓库的 `sdk` 目录。 |
| 包内找不到示例客户端 | 发行包路径为 `automation/fxstudio_client.py`；源码仓库路径为 `tooling/fxstudio_client.py`。 |
| Agent 没有显示 IDE 窗口 | 正常；skill 使用后台会话，GUI 会话独立。 |
| `BUSY` | 轮询当前操作，等完成后再提交该会话的下一条命令。 |
| `REQUEST_KEY_CONFLICT` | 同一 key 只能重试完全相同的操作；新操作使用新 key。 |
| 请求超时，不确定是否执行 | 记录 stderr 提示的 `requestKey`，用同 key、同参数重试，避免重复按键或写内存。 |
| 需要取消构建 | `operation ID --cancel`，然后继续查询直到终态；关闭终端不等于取消。 |
| 截图为空或没有图片 | 停在绘制后的断点；新建 snapshot 操作，并等它完成后导出。 |
| helper 启动失败 | 查看本任务 state 中的 `bridge.log`；不要删除仍被使用的锁文件。 |
| GUI 提示 WindowsBase 或双击闪退 | 使用 r1 修正版，并运行包内校验脚本；skill 不能代替运行库修复。 |

## 设计边界

Skill 负责工程工作流、发现参数和解释结果；Python helper 只管理连接、生命周期与
图片导出；现有 Agent 继续负责异步操作、重试去重、取消、事件与调试状态。
没有再实现一套编译/调试业务协议。所有领域命令仍由 `discover` 返回的 schema 定义。
不需要安装第三方 Python 包，运行时不需要连接在线模型服务。

GUI 会话接管、真机调试、完整 Casio OS/USB 和 C++ 异常/线程均不在现有支持范围。
只报告实际构建、模拟器和断点验证结果，不能把模拟器测试写成真机通过。
