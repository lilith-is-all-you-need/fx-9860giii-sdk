# 工程经验迁移与开发手册

2026-11-15 从相邻 KhiCAS 项目迁入。旧项目继续暂停；本目录服务于新的 Fx Studio SDK。
经验和可执行模板分开保存，模板不含 Giac 数学内核或其运行库。

| 内容 | 入口 |
| --- | --- |
| 63 个故障案例与原始证据定位 | [KhiCAS 案例集](KHICAS-CASEBOOK.zh-CN.md) |
| 可迁移的工程方法 | [跨项目经验](CROSS-PROJECT.zh-CN.md) |
| 怎样应用到本 SDK、哪些不能照搬 | [采用说明](ADOPTION.zh-CN.md) |
| 库、工具链和脚手架操作 | [操作手册](LIBRARIES-AND-SCAFFOLDS.zh-CN.md) |
| 可复制工程和证据模板 | [scaffolds](../../scaffolds/README.md) |
| AI 使用入口 | [fxstudio skill](../../skills/fxstudio/SKILL.md) |
| 迁移来源与校验 | [迁移清单](migration-manifest.json) |
| 本次实际构建、回放与工具检查 | [验证记录](VALIDATION.md) |

案例集与跨项目经验保留原记录的详细内容，链接转换成原工程证据路径以方便独立阅读。
本仓库未复制原 audit、大型二进制或第三方数学源码；迁移清单记录原文 SHA256、
目标 SHA256、原始归档身份和转换规则。因此旧案例的“已修复/实机确认”仍仅属于
其当时对象，不能作为新 SDK 的实机验证。

当前 SDK 已有构建服务、异步调试、ELF/G1A 全 LOAD 内容比对、哈希绑定和临时会话。
本次新增工具只补源码身份、预算依据、失败回滚示例和观察记录，不重写这些服务。
