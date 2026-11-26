# WALL-E V2.2 R478 当前命令的独立数据库路径隔离

日期：2026-11-25（香港时间）

## 基线与隔离

开发 `codex/2.2` 与集成 `codex/2.2-integration` 分别使用自己的 Python 3.13.5 `.venv` 和当前未提交源码。每个分支的专项在 `TemporaryDirectory(prefix="walle-v22-r478-path-isolation-")` 下创建两份独立 SQLite：`dev/wall-e.sqlite` 与 `integration/wall-e.sqlite`，两库初始化为现行 Schema 151。数据库文件路径和对应进程锁均不同，没有监听端口、网络、模型、用户服务或生产数据访问。

## 当前业务命令与交叉读取负例

每份数据库分别通过当前业务命令创建需求和空白文档；两边主键有意相同（需求 1、文档 1），标题／正文／文档名不同。仅开发库创建并保存人工草稿。释放各自的写锁后，分别构造新的 `Database` 句柄并重取锁：开发库读回自己的需求和草稿；集成库读回自己的需求与文档，并得到 `MANUAL_DRAFT_NOT_FOUND`，无法借相同主键读出开发库草稿。两侧均打印 `R478_DATABASE_PATH_ISOLATION:PASS`，负例结果一致。

临时命令为各工作区 `..venv\Scripts\python.exe -c <临时脚本>`。脚本只在本轮进程内调用现有需求、文档与草稿命令／查询，没有新增测试源码。导入测试辅助函数各产生一条 Starlette TestClient 弃用警告；没有实例化 TestClient 或调用网络传输。

## 清理与结论

临时目录在成功或异常后自动清理，包含 SQLite、锁文件和数据。无服务进程、浏览器或端口需要回收。当前业务命令在明确传入的不同 SQLite 路径上按库隔离，且即使对象 ID 相同也未跨库回退。该结果不验证环境配置解析、不同 UID／目录权限、真实普通服务 HTTP、浏览器或原生 Linux 主机边界；服务级当前源码验证仍待 Linux 独立来宾。关联持久化读回见 [R477](windows-current-command-reopen-readback-r477-2026-11-25.md)，HTTP／服务进程限制见 [R476](windows-current-business-command-and-asyncio-boundary-r476-2026-11-25.md)。
