# Probe3：GIII 文件页映射与 OS 交接探测

这是实机探测程序，尚未收到 Probe3 的实机结果。它不启动完整 KhiCAS，不修改固件。
测试 BIN 为自行生成的 2,094,444 字节数据及小型 SH 函数，与被研究的 KhiCAS 文件等长，
覆盖 512 个 4 KiB 页；不包含 KhiCAS 或 Casio 固件。

## 计算器操作

将发布包中的以下六个文件复制到计算器存储内存根目录，保持名称：

- `Probe3.g1a`
- `Probe3.bin`
- `Probe3.cfg`
- `P3e4095.bin`
- `P3e4096.bin`
- `P3e4097.bin`

需要约 2.2 MB 空闲存储空间及约 34 KiB 可分配 P1 堆空间（分三次分配）。退出 USB 存储模式后：

1. 打开 **Probe3**，等待自动测试结束。期间可能停留在 `Starting probe / Please wait`。
2. 出现 `Auto checks passed / MENU: switch app` 后，按 **MENU**，选择 **RUN-MAT**，
   确实进入该应用。此步验证 OS 替换应用时的退出回调。
3. 再按 MENU，重新打开 Probe3。它读取原日志，显示 `Saved: SUCCESS` 或
   `Saved: NEED REVIEW`，不会重新跑整套测试。按 **EXIT** 返回。
4. 回传根目录的 **Probe3.txt**。失败或中断也请保留原文件。

直接 EXIT 也能退出，但会缺少“带着 BIN 映射进入 OS 退出回调”的证据，不能替代步骤 2。
若显示 `Probe not started`，回传 `P3Start.txt`；若没有生成该文件，提供屏幕上的原因即可。
未知 OS 指纹会留下 `SKIP_UNRECOGNIZED_OS` 并停止，不尝试猜测地址。
实机 03.70.0200 的镜像未提供；它是否匹配已知核心代码，由 Probe 在本机检查。

程序只写自己的 `Probe3.txt`（64 KiB）、`P3Work.tmp`（512 B）和启动失败记录
`P3Start.txt`（512 B）；发现同名非本程序文件会保留它并停止。
已有 Probe3 日志意味着“重入读取”，不会覆盖或自动重测。需要重测时，先把旧日志另存到电脑，
再移走计算器上的旧 Probe3.txt。配置和 BIN 必须使用同一次构建的配对版本。

## 探测内容

- 验证 SH7305、P1 栈、MMU 状态及六段 OS 核心代码指纹，再从实际指令的常量池推导
  文件偏移查询入口、512 项 RAM 页表及软件替换游标；没有把某一固件的 RAM 地址写死。
- 查询 BIN 每一页的真实物理地址，以 Bfile 内容逐页核对，再检查整个文件的 FNV 校验。
- 对首字节、4095/4096/4097 等偏移、最后一个有效字节，以及 4095/4096/4097 字节文件做核对。
- 借用 OS 页表，按打乱顺序校验并调用所有 512 页的小函数，两轮执行强制跨越 55 个可轮换槽位。
  OS 缺页路径只查 RAM 页表；不在缺页异常中调用 Bfile。
- 文件打开、读取、写入、关闭前后比较页表；恢复 OS 映射，重新查询地址，再校验执行所有页。
  每次开始映射前重新查询，避免探测日志写入本身使先前地址失效。
- 建立一个 RAM 影子页，修改返回常量并执行；保留对齐、缓存维护指令与独立 P2 常驻代码。
- 定时器在普通映射下调用目标末页；文件操作期间跳过目标调用，记录跳过次数。
- MENU 替换时常驻退出回调恢复原页表、重新查询 BIN、校验并执行第 470 页的目标退出函数，
  然后恢复原映射、写日志并在原 G1A 代码中释放内存。

文件内容和地址核对为 FNV 校验，不是密码学证明。指纹用于匹配已分析代码，不用作信任认证。
通过以上探测支持文件映射路线，但不能证明全部 KhiCAS 代码、运行库、syscall 或系统时序兼容。

## 构建与验证

使用 SDK 的 `fxide.json`，Debug 调试、Release 发布。无 libc/gint 运行库依赖，保留完整 G1A 布局。
构建后的 `tools/relocations.py` 读取 ELF 的实际重定位信息，修补 P2 常驻区内部绝对地址，
并拒绝越出常驻区的代码/数据引用。Release 常驻区为 9,780 B、231 个绝对地址修补、0 个外部引用。
共享 profile 头在 `src` 内保留副本，以适应原生构建服务的项目复制；回归测试检查副本一致。

`tools/bundle.py BUILD_DIRECTORY` 生成配套 BIN、配置与三个边界文件。
`tools/verify.py --bundle DIR --firmware LOCAL_OS.bin --output NEW_DIR --stress --mode menu`
在新模拟器中执行真实 Probe3.g1a、按键、菜单替换及重入。`--mode exit` 单独检查普通退出。
`tools/verify_failures.py` 检查缺配置、堆不足、外来同名日志、未知 OS 和错误 BIN 校验。
`tools/inspect_result.py Probe3.txt --origin hardware` 汇总回传报告；不会默认把模拟结果标为实机证据。

本轮 Release 在 48 KiB 模拟堆内完成 3.71/3071 碎片及 MENU 压力测试、3.60/3071 普通退出、
3.40/3071 碎片及普通退出，均完成重入；五类拒绝测试通过。
模拟器范围及固件对照限制见 [固件辅助映射说明](../emulator/OS-MAPPING.md)。
