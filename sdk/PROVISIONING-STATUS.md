# 工具链交付状态

2026-11-14，本文仅记录尚未完成的可选 WSL 方案。后续主交付已经转向原生 Windows 工具链；不能把本文对应的 WSL 目录当作可安装 rootfs。原生 GDB 已完成并经过实际模拟器源码调试测试，详见 `dist-toolchain/native-gdb/README.md` 和验证记录。

已完成：

- 校验 Ubuntu base 24.04.5 的 SHA-256：`e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86`。
- 创建独立 WSL1 `FxSDK-Dev-20261114`，安装位置 `%USERPROFILE%\.codex-build-envs\fxsdk-dev-20261114`。
- 从原 `Ubuntu-24.04` 只读复制公开 SDK 的 bin/include/lib/share/fxsdk，未导出用户发行版、未更改原发行版。
- 经临时 Windows 本地下载转发器完成 APT update；转发只绑定 127.0.0.1、限定 Ubuntu 官方域名，APT 保留签名与哈希校验；未修改 Windows/WSL 网络设置。
- 写好构建、取消、Debug 编译器包装器、离线安装、打包、源包收集、C/C++17 smoke 脚本及样例。
- 包装器实际子进程测试通过，涵盖响应文件、Debug 强制选项、去符号剥离、C++ 禁止异常和 Release 保留参数；所有 Python 文件语法检查通过。
- SDK/GCC/binutils 与数学依赖源码已缓存并记录 SHA-256；Ubuntu base 的可取得对应源码已预取，尚有旧版本须更新或另行取得，见 `dist-toolchain/sources/ubuntu/missing.json`。
- WSL 服务停滞后，通过 Windows 直接读取本任务 rootfs 的 APT 索引，预取 232 个官方二进制包并逐个校验 SHA-256，清单为 `sdk/downloads/offline-cache-manifest.json`。这是依赖候选集合，尚未经过 APT 求解或离线安装测试；对应 Ubuntu 源码缓存也未完成，不属于公共 Windows 交付包。

阻塞：Windows WSL 服务从约 01:43 起对所有发行版的新命令均不响应。我们新发行版的 APT install 和 mkdir 都未执行；其 dpkg status 与安装日志仍是原 base 的 9 月时间。只结束了本任务的卡住客户端；一次限定 12 秒的 `wsl --terminate FxSDK-Dev-20261114` 同样超时，已结束该请求客户端。没有终止或修改其他发行版。

待 WSL 恢复后顺序执行（当前目录为项目根）：

1. `python tooling/apt_via_windows.py -y --no-install-recommends install cmake make python3 python3-pil libpng16-16t64 libusb-1.0-0 zlib1g gdb-multiarch binutils ca-certificates git xz-utils unzip pkg-config`
2. `python tooling/apt_via_windows.py -y --no-install-recommends dist-upgrade`，只更新本任务新发行版，以便对应源码版本与保存的官方源索引一致。
3. `python tooling/install_build_service.py`。
4. `python tooling/smoke_toolchain.py`，修复实际暴露的问题，确认 C/C++ 的 Debug/Release 均生成有效 G1A、未剥离 Debug ELF、源码映射和 GDB符号均可用。
5. `python tooling/collect_distro_sources.py`，确认无缺失源包，并补齐许可证文件清单。
6. `python tooling/finalize_toolchain.py` 产生 rootfs tar.gz、安装脚本和校验表。
7. 在另一个全新命名发行版中导入该 rootfs，全程不用下载，再运行 smoke；单独保存干净导入验证记录。不得删改用户已有同名发行版。
8. 若继续该可选方案，与 IDE 实际联调编译、错误显示和取消。调试默认优先使用独立原生 Windows GDB，无需 WSL1 GDB 回环连接。

注意：`finalize_toolchain.py` 有源码/验证存在性门禁，但目前还未实际执行；最终交付前需要顶层审查和干净导入测试。默认 C++ 不支持异常/线程，编译器明确使用 `-fno-exceptions`，不混入 KhiCAS 的 SJLJ 实验。

Debug 用户编译禁用 LTO，但最终链接必须允许 GCC 14.1 插件处理预编译 gint/fxlibc 中仅有 LTO 的对象；SDK 库仍保留优化，其内部源码调试受限。具体约定见 `BUILD-SERVICE.md`。用户已明确暂不重启 WSL，因此不要自行继续调用或重启任何 WSL 发行版。
