# WALL-E V2.2 R477 当前业务命令与 SQLite 重开读回

日期：2026-11-25（香港时间）

## 基线与范围

开发 `codex/2.2` 与集成 `codex/2.2-integration` 均从未提交的当前工作树执行，HEAD 均为 `deacba8a9545122f35a2f85c125a354205e06461`。分别使用各自 Python 3.13.5 `.venv`、临时 SQLite 和临时进程锁；未连接网络或模型供应方，没有使用 8001，也没有启动 HTTP、Uvicorn、浏览器或监听端口。

## 当前命令路径及重开读回

每个工作区以临时内存脚本调用当前代码中的 `create_requirement`、`create_document`、`start_manual_draft`、`save_manual_draft`、`get_requirement`、`get_current_document` 和 `get_manual_draft`。草稿正文由当前编辑快照验证／身份分配逻辑生成。命令执行后退出原 `ProcessLock`，使用同一临时数据库路径构造新的 `Database`，重新校验现有 Schema 并取得新锁，再读取需求、正式文档与草稿。

两侧均通过：需求读取成功且工作状态为 `MANUAL_EDITING`；文档当前正式正文仍为空；草稿 ID 和保存正文在重开后与保存回执一致。重开正文 SHA256：`96865058af6dab9778d8ca6885f84346ec012e23b7405cb70a75746314065c1a`。各侧结果标记 `R477_COMMAND_REOPEN_READBACK:PASS`。运行命令为各工作区 `.\.venv\Scripts\python.exe -c <临时脚本>`，脚本仅存在于本轮进程内，没有新增测试源码。

首次临时脚本误将保存回执假定为 `data.manual_draft` 嵌套结构，触发 `KeyError` 后立即停止；核对现有编辑测试后改为读取 `data` 中直接返回的草稿对象，再分别重跑，两侧通过。该失败来自临时核验脚本的数据形状假设，不是业务命令失败。两次执行还各有一条导入 Starlette TestClient 时产生的弃用警告；测试未创建 TestClient 或网络传输。

## 清理、结论与边界

`TemporaryDirectory(prefix="walle-v22-r477-persistence-")` 在成功或异常退出后删除本轮 SQLite、锁文件及目录。没有生产服务或用户数据副作用，源码、Git 索引和 HEAD 未改动。该结果验证当前命令与 SQLite 在重新取得数据库锁后的持久读回；不等于应用进程重启、API／前端接入、双环境交叉拒绝或 Linux 原生验收。Windows HTTP／服务启动边界见 [R476](windows-current-business-command-and-asyncio-boundary-r476-2026-11-25.md)。下一步仍需在独立无网 Linux 来宾对当前两工作区启动真实普通服务、完成 HTTP 操作与进程重启读回，并验证开发／集成数据交叉拒绝。
