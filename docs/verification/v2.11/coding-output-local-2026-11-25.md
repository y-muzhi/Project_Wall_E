# 代码产出本机联调

2026-11-25（香港时间）。用户要求在本机验证从仓库与固定提交到候选、检查、接收和本地 Git 提交。沿用事项 22 的固定程序及 Windows 保护，试验使用独立数据库与临时测试仓库。正常 8001、用户仓库及真实模型不用于本轮测试。

## 已取得的证据

- 固定后台包 `66cdc1d6124b115f67540ce5d5a3677d69f37393546f4ed8f23a5970ec49b6ce`，Guard `0cb957dd38ae1c60750817dd75c5911001b2116ece69f967e689489d57aea02a`。实际安装器完成系统登记及复核，Windows 服务以 SYSTEM 报告运行。测试隔离后端能够启动和受理登记。
- 第一轮试验仓库误放在 Guard 已保护的配置目录内，产品以 `SOURCE_UNSUPPORTED` 拒绝，修正为独立目录。第二轮固定 Git 运行至 PREPARE、CREATE_SUSPENDED、RESUME、STOP 均收到确认，登记在 300 秒时为 `UNKNOWN / EXTERNAL_RESULT_UNKNOWN`。通信各阶段主要往返约 48 秒；SCM 最终报告 STOPPED，原隔离回执保留，测试目录解锁后已清理。基本身份认证和 Git 执行已经发生，仓库未保存。
- 原生后台程序包成员抽样 100 项。实际 Windows 身份、权限、原句柄和字节核验 0.342 秒，文件句柄的反复路径身份检查占主要时间。移除构造期重复的全包与单文件读取，保留受保护原句柄打开、清单核对、每个命令授权前后完整核验，300 秒上限不变。受保护程序与 SCM 生命周期 62 项专项及定向 Ruff 通过，重建包待实机复测。
- `test_v20_guard_control_git_transport.py` 的 `PROJECT_CHECK_HANDOFF` 联调 1 项通过。使用真实 Windows 管道、固定 MinGit、NTFS、SQLite 和受控检查命令，核对原候选文件内容、检查及角色交接。OpenCode 会话、模型与 WFP 使用测试夹具，未作为产品准入。
- `test_v20_native_delivery_guard.py` 与 `test_task_delivery.py` 共 6 项通过。前者实际在 SHA-1 和 SHA-256 临时仓库写入目标引用、验证新提交和保留当前工作区／索引；后者校验接收、待交付与中断恢复接口，报告与交付预览使用隔离证据夹具。这两批测试不代表生产从模型写代码到交付的同一次运行。
- 正常目录 `code20-r3` 当前无 `EXECUTOR`、`CAPABILITY` 或价格选项，现有执行配置 `readiness()` 固定包含 `Q20-MODEL` 且返回未就绪。START 会拒绝。正式 OpenCode 程序与运行闭包、系统 TASK 隔离配置和 Coding 供应方证据仍是实际阻塞，不能用测试夹具或未验证快照启用正式运行。实际 8001 GET 再次验证 EXECUTOR、PRICE、CAPABILITY 均空，三个 MODEL 选项均未就绪。

## 修订 4 的实机复测状态

- 短时回归 `test_v20_delivery_git.py::test_complete_target_and_exact_commit_use_real_git` 共 2 项通过，覆盖两个真实对象格式、完整候选树及实际可读的目标提交。
- 提速 Guard 包 `455d77065aa93c2aa88eb7fa83b4fb9889f7762a765e9196971da0d8c28f219e` 已通过固定源码、运行探针、完整成员核验和系统安装。Program Files 目录为 `C:/Program Files/WALLE.V211.RepoPerf`。安装请求 `a8dc46b129b666cc7f57793e09a6a465ceea276de7e696d740a7e451f8a1212c`，隔离后台清单 `9241bca24fae183c2730dee530589336890afb0ae0e8ac06be3a61ccae43273c` 已通过只读配置预检。
- Windows 启动确认返回操作已取消。修订 4 服务 STOPPED／PID 0／Win32 1077（尚无实际启动），实机登记复测未执行。上一套测试 Guard 也已停止，8001 仓库请求实测 200、0 条。独立测试目录和临时构建依赖已清理。
- 本轮访问 OpenCode 官方固定源码下载入口。直连超时，已有本地代理下载至 6 MiB 后达到时限，分段请求的 TLS 握手失败。未取得完整 ZIP 或正式可执行安装。原调用和失败均发生在下载公开资源阶段。模型与计数请求为 0。
