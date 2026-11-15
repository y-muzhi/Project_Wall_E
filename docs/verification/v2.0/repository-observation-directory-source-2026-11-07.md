# V2.0 仓库观察原目录与回执验证

2026-11-07，V2 未提交工作区，Windows／隔离 NTFS、SQLite 3.54.1、db20-r18。应用代码未改固定 Schema 来源、业务数据或用户服务。依据[待合入迭代](../../iterations/pending/v2.0/WALL-E.C02仓库观察原目录句柄细化_V_2.0.md)。

- tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_guard_control_git_transport.py -k metadata_directories。真实自有双进程、普通账户、真实原目录对象。拒绝错 scope／文件身份／较宽的列目录权限。Guard 测试禁止调用按路径开目录的入口，真实复制及身份核对通过，原后端租约仍有效。最终同时模拟原关闭失败，拒绝继续使用、保持原 owner 并在恢复关闭后释放。最终 1 项通过（2.34 秒）。
- repository_observation_publish.py 的 C02 原启动及发布沿已接收回执，定向覆盖启动时原仓库绑定、禁止再次启动、原观察发布及重放、提交回执丢失、无回执伪操作。数据库／接口扩大结果见下。
- Ruff format 检查 243 个应用文件，改动后端模块 lint 和 git diff --check 通过。当前单元是原目录证据、原接收与应用事务边界。未接三次固定 Git 派发、C02 HTTP 或实际 SYSTEM 保护服务。

合并管道、固定 Git 对象及应用回归的首轮达到 260 秒总时限，诊断时栈位于现有原始 Git 对象用例，整组无结论。首次单独运行三份应用文件在 150 秒总时限前完成 23 项且未报告断言失败，整组无结论。随后分开应用发布与查询验证。固定工作树／分支读取及目录句柄单独以 -k 'metadata_directories or fixed_metadata_commands' 运行，3 项通过（63.77 秒），含固定 MinGit 两种对象格式和新的跨进程句柄与关闭边界。

最终在独立测试临时目录分组运行。test_repository_observation_publish.py 10 项通过（62.83 秒）；test_repository_operations.py 与 test_repository_reads.py 合计 16 项通过（93.61 秒）。两组使用真实 ASGI、隔离 SQLite 和原接收回执，覆盖已登记仓库绑定、启动拒绝重入、未接收的伪操作拒绝发布、回滚、丢提交回执及查询。应用夹具仍人工提供已完成的 READ_REPOSITORY 证据；不能据此声称真实 C02 派发已接。实际原始 Git 对象扩大未完成，后续相关能力收口时再核。
