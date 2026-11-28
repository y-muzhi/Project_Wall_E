# V2.2 R467 固定 ARM64 后端专项对照

2026-11-25（香港时间）。无网 Ubuntu 24.04 AArch64 仿真来宾，QEMU TCG PID 53104，无宿主端口转发。固定 ARM64 运行包 `d1dd25086a50ee3ec01af0ccb345b28ae52b6b85231590fcc57b47a332976c98`。读取 [R462](local-arm64-runtime-dual-environment-r462-2026-11-25.md) 的已封存关机盘，另建独占覆盖盘及测试临时根。

- 从 [R464 x86_64 专项](local-x86-release-compatibility-unit-r464-2026-11-25.md) 复用同一份源码及测试，逐项验证 1,896 个输入的摘要。运行驱动使用 ARM64 包摘要，原测试文件字节保持。
- 以该来宾固定的 CPython 3.13.18／SQLite 3.54.1，关闭外部 pytest 插件及缓存，执行 `backend/tests/infrastructure/test_v22_*.py` 共 24 文件。**304 项通过、2 项平台跳过**，一条既有 Starlette TestClient 弃用提示，61.85 秒，来宾退出 0。汇总计数与 x86_64 同范围一致。
- 本次覆盖固定 AArch64 可执行文件和实际 Linux 测试；另有普通环境业务联验。物理 ARM64 主机、云网络和生产接入另验。
