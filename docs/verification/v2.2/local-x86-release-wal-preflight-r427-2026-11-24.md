# R427 固定发布开放前的 SQLite 边文件

2026-11-24（香港时间）。独立 `codex/2.2`，无网 Ubuntu 24.04.5 x86_64／ext4，固定包 `c8a54e6342272206dec15db198a2cc2a4910760576722a2f490cbc7f0addc702`。CPython 3.13.18、SQLite 3.54.1。Caddy HTTPS 9443 和两个实际 WALL-E 只在来宾回环。采用独立测试部署输入和测试数据库。

- 使用实际 SQLite 的 EXCLUSIVE WAL 模式，由试验应用身份持原稳定锁提交一笔测试变更后退出。数据库主文件不变，存在有效 `-wal`，未生成 `-shm`。实际 `serve-release-open` 已持原发布控制和真实 Caddy 验证。在修复前版本上，虽然启动返回 `RELEASE_OPEN_UNVERIFIED`，Linux inotify 捕获创建 `-shm`，并验证它留在数据目录。独立测试进程按故障退出 1。[SQLite WAL 的只读访问及 EXCLUSIVE 模式](https://www.sqlite.org/wal.html)
- 通过普通启动范围的预检入口调用现有 SQLite 预检。固定发布范围在同一稳定锁下先检查 `-wal`、`-shm`、`-journal`，通过后才进入既有预检。恢复代次仍经原冻结恢复分支。普通环境原有数据库预检继续使用原逻辑。
- 重新生成独立来宾及故障数据库，实际开放入口同样拒绝。Linux inotify 未发现数据目录创建、移入／移出或删除。数据库主文件、原 WAL 摘要、关闭控制字节保持，无应用套接字、无原开放回执，原操作的只读状态仍为 `RELEASE_OPEN_NOT_PREPARED`。另一站原草稿持续可读。进程及来宾退出均为 0。
- 用无边文件的独立测试库走实际正向开放。目标以新普通运行读回原正文，旧部署准备和旧开放动作都拒绝，原开放回执摘要、数据库 inode、稳定锁及原正文保持。验证及来宾退出 0。另一独立来宾在固定目标开始普通重启之前留下有效 WAL。普通入口正常启动，实际需求详情读到 WAL 内已提交的标题，原正文和原开放回执仍可读。另一站连续，旧开放动作仍被拒绝，来宾退出 0。
- 在同一固定运行包下用 `pytest -q --tb=short -p no:cacheprovider` 执行 29 项本批旧版本对照，26 失败、3 通过。四项新增边文件检查覆盖三种文件及无边文件路径。当前 `backend/tests/infrastructure/test_v22_*.py` 共 248 项通过，报告一项既有 Starlette TestClient 弃用警告。Windows 同一工作线程入口 6 项回归通过。Ruff 格式 667 个相关文件、定向静态检查和 Git 差异空白检查通过。

正式候选、ARM64、异机仓库及生产切换另行验收。
