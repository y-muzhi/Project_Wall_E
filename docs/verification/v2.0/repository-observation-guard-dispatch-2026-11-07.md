# V2.0 C02 原元数据命令与观察发布验证

2026-11-07，未提交的 V2 工作区。Windows、项目锁定 Python、SQLite 3.54.1、db20-r18、MinGit 2.56.0.windows.4。使用自有双进程、隔离数据库与含链接工作树的真实临时 Git 仓库。受保护后端程序鉴权用测试端口，尚无正式 SYSTEM 服务安装。规则见[待合入迭代](../../iterations/pending/v2.0/WALL-E.C02仓库观察原目录句柄细化_V_2.0.md)。

- tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_guard_control_git_transport.py -k fixed_metadata_after。首次两例在错配探测之后因测试提前关闭未核清的 STDIO 而失败。保留生产保护，测试改为沿同一个探测 scope STOP 并验证原 fence，确认未创建后关闭。修后两种对象格式通过（45.46 秒）。
- 接上原 C02 接收／读取步骤、一次保留三条范围及现有私有 MAY／ACK 后，同一真实管道两项通过（61.38 秒）。分支先于工作树时在发送前拒绝，重复预留拒绝，配置 nonce 错配不创建进程，正常结果全部从原 scope STOP／RELEASE。共享派发、原登记 actor 与固定 Git 协议组合 22 项通过（23.29 秒）。这两项是接最终观察保存前的结果。
- 最终 test_v20_guard_control_git_transport.py 整组 13 项通过（143.77 秒）。两种对象格式覆盖真实管道、原 C02 SQLite 回执、固定 Git、三作用域逐个关闭、错配／跳序拒绝。互换原 stdout 被拒且原步骤保留 RUNNING／PENDING，随后真实输出发布原观察，原操作与两步骤成功，重读返回同观察 ID。其余管道覆盖原登记、连接重用和丢回执后的清理。
- 最终 test_repository_git_dispatch.py、test_repository_observation_publish.py、test_v20_guard_control_git_version.py 合计 30 项通过（84.91 秒）。原 in-process 固定 Git metadata 读取 -k fixed_metadata_commands 两种对象格式共 2 项通过（59.92 秒）。后端 Ruff format 243 个应用文件、改动模块 lint、git diff --check 通过。保留原 db20-r18，正常服务与业务库未操作。本批通过既有程序准入测试端口，尚未验证正式 SYSTEM、LPAC 或安装包。
- 现行 C02 生产队列、HTTP 和前端刷新动作仍待接入。
