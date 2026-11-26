# R450 用原生 pip 复验固定 Linux 构建工具

2026-11-25，独立 `codex/2.2-integration`，HEAD `deacba8a9545122f35a2f85c125a354205e06461`，R447 未提交源码。Ubuntu 24.04.5 x86_64、ext4、QEMU TCG，无网卡和端口转发。来宾核对 128 个已变更源码文件的原字节 SHA256。固定运行包摘要 `0241128f2faa82bcc1f34d3f87196b0b817333caec2d070bf5a91f0cd3998e9e`，CPython 3.13.18、SQLite 3.54.1 和 19 个宿主库。

普通运行启动不把 pip 加入导入路径。运行包元数据实存经过封存索引验证的 `pip-26.2.2-py3-none-any.whl`，SHA256 `fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70`。在测试进程内先复验运行清单、依赖清单、实际加载和宿主映射，再加入这份 wheel，核对 `pip` 与 `pip._vendor.packaging` 均从它导入。用 `python3.13 -I -B -S` 执行现有 `backend/tests/infrastructure/test_v22_*.py`。277 项通过、2 项跳过、1 条既有 Starlette 弃用警告，42.68 秒，来宾标记 `WALLE_QA_DONE:0`。包括原生 vendored packaging 的 wheel 发布专项，离线使用模拟下载响应验证校验与硬链接发布。

WHPX 首次启动被宿主拒绝（`0x80070005`）。第一次 TCG 的测试脚本将运行清单路径误写为 `metadata/`，未开始测试，退出标记为 1。修正路径后在新的覆盖盘通过。底盘文件大小、修改时间与原固定摘要核对保持。该证据覆盖 R447 使用临时适配的用例。此次未重复下载 wheel 或生成正式候选。三次启动对应的本轮临时覆盖盘、归档和日志已清理，原来宾底盘保留。
