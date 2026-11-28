# R365 Windows 原维护兼容回归及固定 Linux 边界

2026-11-24（香港时间）。独立 `codex/2.2`。按既有 `tools/python-v20.py --probe` 验证 SQLite 3.54.1 专用 Windows DLL。使用 `tools/quality_python.py` 守卫及已有维护专项。它约束 SQLite 到本轮临时区域，拒绝外网以及原业务目录和本地凭据。

- 7 份旧 V2.0 数据结构和维护测试共 **38 项、19 个子项通过**，1 条现有依赖弃用提示。覆盖固定 Schema、临时库捕获和演练、维护 CLI、回执及资源保护。真正子进程崩溃专项不在本批。
- 早期在 Linux 把 Windows 维护专项一起执行，实际旧接口按 `LOCAL_ABSOLUTE_PATH_REQUIRED` 拒绝。当前版本的 Linux 维护和受管发布按 [R358](local-x86-original-release-observation-r358-2026-11-24.md) 的固定 Ubuntu 专项验证。Windows 沙箱 AppContainer 也被原私有包策略拒绝。经系统审批用 Windows 正常用户执行同一检查，短专属临时目录解决了深层历史夹具路径问题。原平台限制和离线守卫均有效。
- 整个 `backend/app` 的 Ruff 格式检查通过，本轮改动 Python 文件的 F/I 检查通过。额外的全后端 F/I 盘点前后均为 262 项，逐文件和诊断无新增。前端格式及类型另见浏览器修复记录。
