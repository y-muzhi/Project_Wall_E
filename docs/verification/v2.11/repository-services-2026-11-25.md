# 仓库登记服务部署验证

2026-11-25（香港时间）。当前任务为部署 8001 仓库登记所需能力，然后核对 `coffee-mini`。原 8001 由普通 OpenAI 启动器提供，原登记接口返回 503，原回执为 `NOT_FOUND`。两套历史 Guard 服务均停止，新目标在预检时不存在。

## 普通身份下的检查与程序准备

- 原 Guard `guard-prepared-20261115-1525-private-owner`、安装工具 `guard-installer-prepared-20261114-2059` 的固定输入可回读。历史普通探针后台入口只支持 Schema200，不能接管正常 Schema210 库。
- `backend/frozen_backend_entry.py` 接入显式 `--schema-version`，默认 200。`tools/windows_backend_package.py` 纳入两个版本的固定来源，发布前运行冻结后台的两个对应 `--verify-runtime` 检查。
- 构建工具按 `backend/requirements-build.lock` 校验 SHA-256 后安装到临时工作区。相关 Ruff 格式和 `git diff --check` 通过。用隔离 Schema210 库启动 `walle-backend.exe --schema-version 210`，实际 GET `/api/v1/code-repositories` 及 `/requirements` 正常。仅关闭本轮临时进程并清理临时数据库。真实模型和计数调用均为零。
- 兼容后台包 `prepared-20261125-repository-schema210` 共 2,789 个成员，manifest SHA-256 为 `491ac1b348e4c639c35e134138fa6aed88b0d83c3eb11c8652ca8e99d66b4eea`。计划 `guard-bootstrap-prepared-20261125-repository` SHA-256 为 `65657fae1075a2acbb38c1abd0ccccf681b0e4c244f36b732b3aac277805939f`。请求 `guard-installation-prepared-20261125-repository/guard-installation.v1.json` SHA-256 为 `3a470c8d345b833cdbb8ec88bb2abc005af43d8d5ce9440f248f54b153b5e661`。
- 本轮新目录为 `C:\Program Files\WALLE.RuntimeGuard.V2.Repo.20261125`，服务标识为 `ce63060105bc3f59a91cede38dc9b25a94b309aa6d2c2519195a01405da44d83`。部署目标是仓库登记，Guard 的 task／runtime／checks 为空。

## 系统安装与 8001 切换

- 专用安装器经 Windows 管理员确认写入新目录和 `installation-receipt.v1.json`，外层监督程序返回退出码 1。只读查询确认新服务已注册为 `STOPPED`，PID 0、SCM 1077、专用错误 0。回执为 `REGISTERED_STOPPED`，请求摘要与本轮一致。回执在安装尾段复验之前写入，工具退出原因尚未取得。保留现场，未重装。
- 后台登记配置 `data/service-runtime-v211-repository/backend-deployment.v1.json` SHA-256 为 `c7a2628d932e21c7653259c66e2d4fe1871a691ecdd65be4ec41569ee17613dc`。安装后 `tools/inspect-code-deployment.py --kind backend --manifest <固定路径> --sha256 <固定摘要>` 通过，实际 Guard 镜像及私有目录通过普通用户预检。已安装 Guard、后台和部署文件的清单摘要与已准备输入一致。
- 本轮冻结后台来自当前工作区，含事项 20 的待发布本地后端改动。其隔离启动只验证兼容性。生产切换还须确认部署的源范围和现用模型发布一致。
- 随后用同一请求执行 `v20_guard_system_bootstrap_worker.py --start-stop --allow-system-changes`。新 Guard 进入 `RUNNING`，此前 SYSTEM 私有记录初始化阶段已通过。普通后台探针退出 1。部署检查从 SCM 取得本次 Guard 的 PID 后，重现实例进程 `OpenProcess(0x1000 | 0x100000)` 的 `PROCESS_HANDLE_UNAVAILABLE`，Win32 原生错误 5。本次拒绝发生在读取主令牌和核对管道身份之前。未进一步区分两个进程访问位各自的结果。
- 原检查程序停止本轮 Guard。2026-11-25 本轮末只读确认 SCM `STOPPED`，PID 0、Win32 与服务专用退出码均为 0，原安装器与临时后台退出。8001 仍由 PID 53528 提供服务，需求页和仓库接口读取通过，仓库 0 条。本次未切换正常 8001、未恢复 `coffee-mini` 登记、未改变现有进程／令牌访问规则。

## 接续断点

下一步从 `backend/app/infrastructure/windows_guard_service.py` 的 SCM 原进程核对及 `windows_process.py` 的 `ObservedProcess` 权限申请接续。明确普通用户对该项目 Guard 的最小查询、存活观测及其后的主令牌和管道身份核对方案。原 `--start-stop` 已实际执行，不依据旧 1077 状态重复启动。生产切换前还需固定已发布功能范围，避免同时发布事项 20 的本地改动。现有安装目录、回执及固定配置保留。
