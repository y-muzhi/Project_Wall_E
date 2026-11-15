# V2.0 原认证 TASK 动作与平台回收

2026-11-09（Asia/Hong_Kong），Windows 11 AMD64／NTFS，工作树基线 `28a7c9e`。对照 BE 7.3.1—7.3.4、7.4.2、7.4.4。 [独立迭代](../../iterations/pending/v2.0/WALL-E.执行器配置隔离与生效迭代_V_2.0.md)

- 断点 1—10。原受管部署及 WFP 用夹具，Windows 的认证双进程管道、Job、profile 和测试 PE 均为实际接口。原确认和原三个标准 I/O 句柄、原文件和 LPAC、挂起回执及原动作观察闭合。调试发现 I/O nonce 实为 UUID、Job 成员须编码为 JSON 列表，修正后通过。
- 断点 11—17。后端原 NTFS 意图和确认，故障注入本地 CREATE 回执写入失败后只观察原动作并保存原回执，错摘要在后端和 Guard 分别拒绝，实际原线程恢复和重复 STOP 查回。最终实际断连重接复用原 Guard 首端点与同一后端身份，观察并补写原挂起回执后才恢复。
- 断点 18—20。实际原后端退出后监视器关闭原 nonce、停止原 Job 并记录平台证据，用户 STOP 动作保持未发生。WFP 使用夹具，模拟首次规则缺失读回失败，保留 profile；原 RELEASE 重复只读回规则，随后实际删除原 profile。完整 RELEASE 仍为 MAY，OBSERVE 返回已核实的网络和 profile 分项。
- 以 `tools.quality_gate.environment`、`WALLE_TEST_CONTROLLER_POSITIVE=1`、自动清理 `--basetemp` 运行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short`。首轮原完整管道 1 项通过（60.26 秒），加入本地回执失败和部分 RELEASE 后 1 项通过（78.18 秒），实际后端退出专项 1 项通过（73.91 秒）。扩大组合 **212 项通过**（373.89 秒）。单独复跑重连触发控制方关闭竞争，关闭时与原监视同时访问作用域，导致测试私有文件未及时解锁。修正为关闭期间暂停 TASK 监视扫尾、同步核对原停止，以及显式 STOP 成功后登记监视完成。只结束该轮唯一匹配的已挂起 pytest 子进程，原包装器清理其专用临时目录。
- 修复后实际断连重接／原挂起观察／恢复及部分 RELEASE **1 项通过**（81.91 秒），实际原后端退出监视 **1 项通过**（76.45 秒）。另复跑 `test_v20_guard_controller_owner.py`、`test_v20_guard_controller_owner_native.py`、`test_v20_runtime_launch_journal.py`、`test_v20_guard_action_journal.py`、`test_v20_windows_lpac_profile.py` 共 **58 项通过**（16.99 秒）。仅既有 Starlette 弃用提示。应用 310 文件 Ruff 格式、15 应用模块 lint、18 本轮源码／测试文件行尾空白和 Git 空白检查通过。测试进程、临时 profile、监听和目录已清理。
- 正式 SYSTEM／普通后端部署、真实 WFP、固定 OpenCode、业务 START_INSTANCE、原生控制／模型归属、跨控制方恢复和运行目录清理仍待。仓库登记数据库回归受既有 `db20-r29` 摘要差异影响，未执行。
