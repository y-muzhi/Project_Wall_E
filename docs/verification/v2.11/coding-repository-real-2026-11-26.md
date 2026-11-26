# 实际咖啡仓库登记及审阅后台接入

2026-11-26，香港时间。V2.11 事项 22 修订 7。目标为实际 WALL-E 的业务闭环，本轮从真实仓库登记推进。工作区有并行改动，按原源码和受保护清单记录结果。

## 实际仓库登记

- 确认已安装的 `WALLE.V211.RepoHold` 及后台清单 SHA-256 `66cdc1d6124b115f67540ce5d5a3677d69f37393546f4ed8f23a5970ec49b6ce`。临时启动原 SYSTEM Guard，PID 54864。使用其绑定的正式冻结后台，Schema210 隔离库，进程 42636，回环端口 51598。
- 用正式 HTTP `POST /api/v1/code-repositories` 登记桌面的实际 `coffee-mini` Git 仓库。HTTP 202，操作 1。原操作由 PENDING 进入 RUNNING，274.58 秒时读取 `SUCCEEDED`，VALIDATE、SAVE_FACT 均成功。274.63 秒时从真实列表读回仓库 1，Git 对象格式为 SHA-1。试验前后比对源仓库 HEAD 和全部 ref，一致。
- 独立后台退出，核对原 Guard 为 SCM `STOPPED`、PID 0，临时业务库及日志清理。首次管理端标记文件普通身份无法读取，第二次 WMI 服务配置字段为空，另一次 SCM 输出正则转义错误。改用管理员 SCM 配置检查、两端分别观察实际服务状态与同代 PID 后通过。这些失败未进入登记写入。
- 此次登记记录在隔离业务库。正常 8001 使用 V2.11 文档审阅发布，启动器为对应快照的 `tools/openai-service.py`，实测监听 PID 51052，当前保留使用。

## 后台兼容修复

- 固定后台在显式选择 `WALLE_FORMATION_SCHEMA_LAYOUT=db21-document-review-r1` 时使用与 OpenAI 正常启动器相同的审阅服务入口，继续校验固定 SQLite、Schema、部署和原 API 路由。缺省 200 和普通 210 沿用既有入口。构建加入冻结程序的审阅布局探针，保持前两项。
- 第一次将选择接入应用工厂后发现该文件属于 Schema200 的冻结来源，旧发布按预期拒绝。撤销该改动，在既有审阅专用启动边界复用同一逻辑；Schema200 固定来源字节未变化。第一次构建中审阅常量导入早于 SQLite 激活，随后移至激活后。
- 以虚拟环境 Python 调用 `-m backend.frozen_backend_entry --verify-runtime`，固定 SQLite 3.54.1 下三种布局的源码入口探针均通过，未知布局拒绝。实际临时审阅库启动后，仓库和执行配置 GET 返 200，空列表符合该库状态。退出时临时日志曾短暂占用，已按原路径清理。
- 当前下一业务门槛为执行配置版本。隔离实际 API 的执行配置列表为 0，正式基础快照接口要求有效的 `execution_profile_version_id`。真实 TASK 的网络、模型、价格及配置发布仍未准入，未进入真实任务执行或向桌面仓库交付提交。本轮未触发模型或计数 API。

## 冻结包和下一次配对

- 项目固定哈希构建工具生成 `backend/distributions/windows/b-review-211`，后台清单 SHA-256 为 `93bcc9731de472de7ab835b54e99a118de08d167527c34e240e5aa39789e3431`，2600 个成员。构建实际运行了 Windows 二进制的三项布局探针。前端按已有 `WALLE_FRONTEND_DIST` 由外部目录指定。用新二进制、实际临时审阅库和已编译前端启动，仓库与执行配置 GET 均为 200。该包为当前工作区的候选，尚需核对正式发布范围。
- 18 项固定入口与 Guard 探针回归通过，格式检查及改动差异检查通过。候选实际回环启动后退出。确认试验和构建工具临时目录均为 0，原 Guard SCM `STOPPED`、PID 0、退出码均为 0。正式 8001 仓库列表仍返回 200、0 条。
- 新配对计划 SHA-256 `64d842aa730a59a3614d0f6abddce1a2aa629ff53eb6bd7e33f877a27256ecf7`。已生成并核对固定安装输入 `backend/distributions/windows/review-reg-request/guard-installation.v1.json`，SHA-256 `61e6f3a4cd31847dfb169f871b88fe9921b5e99798ad7c4964d6128046daeae7`。本轮只准备配对，不安装候选或切换 8001。该配对覆盖仓库登记，正式任务执行仍须另外取得网络与模型计费证据。
