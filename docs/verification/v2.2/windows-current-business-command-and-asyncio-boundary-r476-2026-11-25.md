# WALL-E V2.2 R476 当前业务回归与 Windows ASGI 边界

日期：2026-11-25（香港时间）

## 基线与隔离

开发 `codex/2.2` 与集成 `codex/2.2-integration` 的 HEAD 均为 `deacba8a9545122f35a2f85c125a354205e06461`。每个用例使用对应分支的 Python 3.13.5 `.venv` 和独立临时 SQLite；模型环境变量已移除。没有连接网络供应方，没有使用 8001，也没有更改业务源码、Git 索引或 HEAD。

## 通过的当前业务命令回归

两分支各自运行：

`python -m pytest backend/tests/requirements/test_v15_foundation.py backend/tests/documents/test_v15_documents.py backend/tests/documents/test_v15_editing.py -k "not http" -q -p no:cacheprovider`

两侧均为 **27 passed、3 deselected**，分别约 88 秒。通过范围包括需求创建、25 种状态迁移、并发与幂等、初始化和失败回滚；空白文档／固定框架、来源与Revision、元数据／归档；人工草稿保存、版本冲突、取消／恢复、块身份与失败回滚。`-k not http` 排除三个名称含 HTTP 的用例；排除项为 `test_http_new_contracts_replay_errors_and_removed_initialization`、`test_actual_http_document_paths_and_strict_target_parameter`、`test_actual_http_edit_requires_document_session_key_and_returns_real_effect`；它们没有完成，本结果不包含 API 路由、FastAPI 生命周期、TCP 服务或浏览器验收。每侧有一条 Starlette 对当前 `httpx` TestClient 组合的弃用警告。

文件名保留 V1.5，但夹具使用现行 V2.2 请求字段和行为；它们是当前业务命令与真实 SQLite 证据，不代表生产服务已接通。

## HTTP 与服务进程边界

两分支的聚焦同步 `TestClient` HTTP 用例在已通过命令用例之后停住；未得到响应断言。另用 `faulthandler` 做最小诊断，Python 堆栈停在 `asyncio.run()` 创建 Windows Proactor 事件循环：`ProactorEventLoop._make_self_pipe` 调用 `socket._fallback_socketpair`，随后阻在 `socket.accept`。数据库初始化阶段标记尚未输出，应用、数据库和 HTTP 路由当时均未运行。另在隔离子进程中显式采用 `WindowsSelectorEventLoopPolicy` 新建事件循环，5 秒内同样未创建完成；父进程通过超时终止并回收该子进程。仅切换 Windows 事件循环策略不能绕过本机回环限制；当前 Python `socket` 模块也没有 `AF_UNIX`，无法改用本地 Unix socketpair。R475 服务进程就绪失败与此相符，但该诊断不能替代 Linux 服务实测。

因此 Windows 本轮未能验证真实 API 路由、Uvicorn 进程、服务重启读回或浏览器流程；本机事件循环在应用启动前遇到回环 socketpair 阻塞，不作为 WALL-E 业务实现失败。`wsl.exe` 命令存在，但 `wsl --list --quiet` 显示没有 Linux 发行版，`vmms`、`vmcompute`、`LxssManager` 服务项不可用；QEMU 不在 PATH，未复用其他任务的 `R441` 临时目录。

## 清理与下一步

两分支 pytest owner 目录在用路径和标记核对后清理，临时 SQLite 未保留。ASGI 诊断停在事件循环创建前，无数据库文件；临时 owner 目录已清理。端口 `18101`、`18102` 无监听。最近的当前源码 Linux 专项证据仍为 [R474](linux-current-source-twin-regression-r474-2026-11-25.md)，但不覆盖普通服务完整业务过程。

下一步需在独立无网 Linux TCG 来宾中，用当前两工作区代码分别验证普通服务进程创建需求、关闭、重启读回，再验证文档人工编辑保存和双环境交叉拒绝。之后再接当前源码浏览器验证。生产接入、候选封存、云采购及 Git 提交／推送仍按既有授权边界。
