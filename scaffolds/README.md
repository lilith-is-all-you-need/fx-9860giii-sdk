# 工程脚手架

这里是维护源；skill 中的 assets/scaffolds 是可独立携带的同步副本。修改此目录后运行
python tooling/sync_engineering_skill.py，并用 --check 防止两份内容漂移。

| 入口 | 用途 | 如何使用 |
| --- | --- | --- |
| guarded-c/ | 固定临时内存、失败注入、取消回滚、退出重入的 C 工程 | 复制到新目录，按普通 Fx Studio 工程编译 |
| evidence-session/ | 绑定产物身份的实机与会话记录 | 从真实设备观察填写，未测保持 not_run |
| tooling/engineering.py（仓库根目录） | 创建工程、源码快照/比较、产物预算、实机记录 | 只使用 Python 标准库，不启动 SDK、下载依赖或上传 |

推荐用创建命令代替手动复制，避免把本机构建缓存和会话凭证带入新项目：

~~~powershell
python tooling/engineering.py new guarded-c C:\FxProjects\guarded
python tooling/engineering.py new evidence-session C:\FxProjects\guarded-checks
~~~

目标目录必须不存在，不会合并覆盖已有工程。工程源码、工具和模板采用仓库 MIT 许可；
这是依据旧项目经验重新编写的独立实现，没有复制 Giac、旧 libfx 或未确认许可的动态加载器。

完整入口见 [工程经验与操作手册](../docs/engineering/README.md)。独立复制脚手架后，
本页的仓库级链接只用于来源定位，实际操作说明位于各模板 README。
