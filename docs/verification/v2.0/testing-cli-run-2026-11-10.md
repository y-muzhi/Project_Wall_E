# V2.0 Testing 受控 CLI 及原运行事务

2026-11-10（香港时间）。master 28a7c9e 本地工作区，Schema200 db20-r36。正式 BE APP-TEST-RUN、7.6.4—7.6.7、7.9。

- Windows 命名管道、LPAC／Job、原退出、停止及清理采用隔离原进程专项。运行 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider，选 TESTING_PROJECT_CHECK 及 test_v20_check_case_evidence.py，14 项通过。可信 CLI 比较原退出码，stdout 不匹配只保留有界摘要，重读原完成记录仍得相同结论。部署准入及 WFP 实际规则使用夹具。
- 相同命令入口专项 test_testing_cli_run.py、test_testing_task_api.py 和 test_testing_report_api.py 初轮 10 项通过。真实 ASGI／SQLite 及原 NTFS 测试包。候选与历史包验证采用明确夹具。覆盖未准入返回 503 且原键仍可使用、同键只返回原 202、执行安装丢失时对已登记原命令核对未派发、不调用 Guard、唯一 UNAVAILABLE 报告及零用例。首测发现受控结果项只允许正式枚举，采用 RESOURCE_MISSING 并重跑通过。
- API27 READY、API33／34 原操作投影及结果资格按 driver 类型重验正在补充回归。真实完整 CANDIDATE／SNAPSHOT 测试报告、CLI 非空 stdin／夹具、HTTP 原端点、浏览器 CHECK_DRIVER 和正式 SYSTEM／WFP 属于后续核验。测试数据、目录和进程均由隔离专项持有及回收。

- 原 STDIN 后续专项使用 70,000 字节有界输入和真实 Windows LPAC／Job 命令。摘要和原预期一致，合计 11 项含 Guard 管道回归通过。命令没有拿到原后端写端，过限或无法确认完成时不生成受控 CLI 通过。实际固定非空 fixture 和正式 WFP 不在此专项。
