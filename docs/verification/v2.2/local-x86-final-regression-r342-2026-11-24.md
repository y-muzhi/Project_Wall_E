# R342 最终源码的锁定 Linux 专项回归

2026-11-24（香港时间），独立 `codex/2.2`，无网卡 Ubuntu 24.04.5 x86_64 来宾。使用固定 Python 3.13.18、SQLite 3.54.1 和运行包 `42c930b863bde38273bc91f777e62733b7d5e200a30c3744fd7eaf95fcb52b25`。在 R327 离线测试副本的独立复制中，加入 R337 两个生产入口、共同生命周期 helper 和扩展回归。通过现有运行时 admit_target、实际依赖验证、SQLite 固定绑定及临时测试目录运行。

`python run-guest.py r342-native disk-r327c-regression.qcow2 offline 285`。13 份 `test_v22_*.py` 共 190 项通过，原有 Starlette 警告 1 条，来宾退出 0。当轮真实宿主和浏览器检查见 [R335](local-x86-two-environment-chromium-r335-2026-11-24.md)、[R337](local-x86-management-lifespan-and-https-r337-2026-11-24.md)、[R340](local-x86-management-chromium-r340-2026-11-24.md)。无真实模型、计数或生产服务调用。

## 两套前端构建

Windows 独立源码和现有锁定依赖中执行 `npm run test`，605 项通过、失败和跳过均为零。`npm run typecheck`、`npm run format:check`，普通 Vite 构建及 `vite.management.config.ts` 管理构建均通过。输出只写本轮专属临时目录。按路径及每文件 SHA256 与保留的 R184 固定资产逐项比较，普通 120 项、管理 3 项全部一致。排序的路径和文件摘要清单分别为 `e8b1a53f60ca54c873bd5b1b46188a9205a8d43b04fb3242b8c6d8eefc8e4043` 与 `5daa5bef2cd0ff40ff8e348419886f527ea8175275897c5e91662f9431c05bec`。普通构建报告既有大 chunk 提示。现有服务、现有构建及工作区源未被构建覆盖。

交付尾查对两个启动器、共用 helper 和扩展回归四份 Python 源执行内存 AST 检查，结果通过。独立 Git 元数据、`codex/2.2` 及原 HEAD 核对通过，`git diff --check` 通过。主项目同期有独立提交，尾查 V2.01 五份资料仍与开工摘要一致。本轮临时目录与 Windows 复现监听已确认不存在，两个保留的固定资产目录可读。
