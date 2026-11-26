# 代码产出本机接续验证

2026-11-26（香港时间）。接续事项 22，在独立 Windows 回环服务、临时库、临时工作区和临时 Git 仓库复测。原 8001 未作切换。真实模型及计数请求均为零。

## 真实 Guard 和仓库登记

- 已安装的提速版 `WALLE.V211.RepoPerf` 显式启动，SYSTEM Guard PID 54772。已固定的普通冻结后台 PID 59884 监听临时端口 57202，使用原配置清单 `9241bca24fae183c2730dee530589336890afb0ae0e8ac06be3a61ccae43273c`。
- 真实接口登记一次临时本地 Git 仓库，HTTP 202，操作 1 由 PENDING 进入 RUNNING，再于 245.06 秒结束为 SUCCEEDED。读取仓库详情及列表取得同一个仓库 1，245.13 秒时完成读回。受控 Git 的 PREPARE、CREATE_SUSPENDED、RESUME、STOP、RELEASE 均获实际确认，限额 300 秒。
- 临时后台退出后提速版 Guard 报告服务循环错误 `0xD7150000` 并停止。真实 Windows 管道专项复现：后台在核验期间退出，原包收尾再次验证已断开的管道，导致已关闭的资源被当成未关闭。使用经核验的原进程句柄副本后复现转绿，权限、身份、字节与消息完整核验路径保留。受保护程序与服务生命周期 63 项通过，Ruff 检查通过。
- 断线修复包 `0a4adcfd0a3cf28b3e8370f6945e17f84670f43232494187f346f8d3dfbef8bc` 通过固定成员、运行时及重复验证，已按固定请求安装至 C:/Program Files/WALLE.V211.RepoHold。真实 SYSTEM Guard PID 62076 接受两个普通冻结后台的鉴权连接，且第一次连接退出后的 28 秒观察中维持原 PID。第二次连接也返回通过。第二次后的额外 28 秒等待跨过安装器 90 秒探针持有期限，监督程序返回尚未运行的错误；复核 SCM 已停止，PID 0，Win32 与服务专用退出码均为 0。两次实际连接已通过，第二次退出后的完整额外观察窗口未取得。

## 实际 OpenCode 和代码交付

- 从官方发布下载 OpenCode 1.19.5 Windows ZIP，完整 SHA-256 `09a6e693157f0887e504f2cf4357a8cbddc5ead5d0dffb9a269dcc47c48640f5`。PE 文件 SHA-256 `d7b473388cb62555970e400ce54cdfb6d6573608beea6f8fdf382cd1a698a3fa`，本机实际 `--version` 得到 1.19.5。固定 OpenAPI Git blob 为 `e064da66bda63c78272f398c940755ecf68b0a3f`。源目录 `backend/distributions/windows/opencode-source-1.19.5`。[官方发布资产](https://github.com/anomalyco/opencode/releases/expanded_assets/v1.19.5)
- 以官方 npm 的 `@opencode-ai/plugin@1.19.5` 和 npm 完整性锁安装离线依赖，忽略安装脚本。运行包目录 `backend/distributions/windows/oc1195-runtime`，3672 文件，引用 `opencode-bundle:sha256:484787028f0237f90b5063c9679e6fff360960f8fd441bb513bc736da389aaee`。项目 `tools/check-opencode-binary.py` 同时通过 ZIP、OpenAPI 及完整闭包检查。
- 真实 OpenCode 在独立临时端口启动。无凭据 `GET /global/health` 为 401，并返回 Basic challenge；用一次性凭据为 200，报告 healthy=true 和 1.19.5。此为普通隔离进程实测，未证明受管 TASK 的 Windows 令牌、Job 与 WFP。
- 实际 OpenCode 向本机模拟供应方发送两次请求，接收一次工具调用并写入临时 `hello.txt`。联调在内存复用 `test_v20_delivery_git.py::exercise_delivery`，将同一份文件按真实候选封存、计算交付差异，随后用固定 MinGit 写入临时仓库的本地目标分支。由新提交 `58c5f5618b24986df3ac821cc620a69a72efdb59` 读取的文件与 OpenCode 输出相同，SHA-256 `58d94dfae6164919f11a9ccace9756ca6db9e4ec8dc43db37893904a58cfce72`。未修改交付产品代码或现有测试夹具文件。临时仓库和目录由联调清理。
- 当前冻结后台及正常 8001 的 TASK 启动尚需正式部署：受管 Windows 隔离证据、实际 Coding 供应方、有效价格／授权和资源准入。隔离配置读取为 EXECUTOR 0、MODEL 3／就绪 0、PRICE 0、CAPABILITY 0。上轮已验接收接口，本轮文件写入到提交使用测试入口，未通过正常页面做同一试验的人工接收。
