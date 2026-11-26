# R379–R381 宿主冻结与原派发 Linux 专项

2026-11-24（香港时间）。独立 `codex/2.2` 的当前工作区。Ubuntu 24.04 x86_64、ext4、固定 CPython 3.13.18／SQLite 3.54.1、31 项锁定 wheel。实际固定运行清单 `d2bdae9782efccede4fd44f169ee86f8a6de7df240364e503b1d2c341acc3c89`。公共 Ubuntu 依赖通过仅工具来宾取得，项目程序和测试仅在无网卡来宾执行。没有宿主端口映射。

- 固定程序实际从 CPython 和 SQLite 官方源码构建。当前 wheel 来源按项目锁及发布摘要核对后，调用项目 `prepare_wheels.py` 和 `seal_runtime.py`。首个脚本阶段使用了错误的清单目录，保留已封存磁盘并在下一隔离启动采用运行包根下的真实清单，非 root 运行 `runtime.py probe` 成功。两阶段只改验证启动脚本。
- R381 对照使用相同依赖和专项文件。旧代码两项故意选择的冻结回归均失败，分别在额度登记前和额度返回后返回 `MANAGED_RELEASE_OPEN_UNVERIFIED`，用例捕获原代码已进入派发。修复版持有环境锁和宿主共享锁才写原派发，在两个时点均返回 `HOST_RECOVERY_HOLD`；后一时点保留原额度，后续按原身份继续且仅一次派发。
- 修复版用固定 Python、`-p no:cacheprovider`、隔离 `--basetemp` 执行 `backend/tests/infrastructure/test_v22_*.py`。15 个专项文件共 209 项通过，1 条现有 Starlette 提示。含 10 项普通启动新边界，核对原准备修订、原操作、启动代次、关闭状态、业务套接字、系统单元、准备持锁写入及派发后释放锁。
- 本轮独立 Windows 前端 `npm run build -- --outDir <专属临时目录>` 成功，120 项普通资产。仍有既有入口 chunk 大小提示。相关后端代码和专项文件定向 Ruff 格式及 F／I 通过。

测试运行包和两组 Python 专项均在独立来宾退出。关闭态真实应用重启、真实宿主冻结、最新固定候选及云端各自验收。
