# V2.0 测试包生命周期与受控证据

2026-11-10，Asia/Hong_Kong。工作区 master 28a7c9e，Schema200 db20-r36，使用独立 SQLite、NTFS 私有包及 ASGI。正常服务、用户库和模型供应方不参与。

- 锁定离线命令为 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/test_testing_pack_seal.py backend/tests/infrastructure/test_v20_check_case_evidence.py backend/tests/test_testing_reference_sets.py backend/tests/test_testing_task_api.py。35 项通过，TestClient 有既有 Starlette 弃用提示。
- 补测命令在同一专项追加 backend/tests/test_testing_report_api.py，39 项通过。新增组夹具只保存 RUNNING 及原顺序子任务，核对 API20／45、有效 READY 时 API28 冷路径 503／无原写入、撤销后各子任务失效。首轮夹具误假定派生 testing_task_ids 为物理列，已改用 Schema200 的原关系表。没有测试通过子任务夹具。原封存清单改字节后 API19 拒绝且未绑定授权，恢复原字节后接续；此变更与报告专项合计 3 项通过。最后单独重跑同生命周期测试，增验原 Runner 登记缺失及 READY 子任务封存字节被改时 API28 拒绝，授权、任务版本、Verification 及原文件恢复事实一致，1 项通过。
- 封存保持 Runner、夹具及输出的原 NTFS 身份。API19 复查固定包、参考注册、真实 Git 登记与零预算批准，独立执行未准入返回 503 CONFIG_NOT_READY／Q20-CHECKS。首轮错误使用了不可作为通用就绪能力的 Q20-BROWSER，已更正并复验，未消费授权或创建验证组。
- API21 要求同摘要最新验证及其完整原子任务事实、实际资产和正负对照。API22 撤销本包，计划撤销同时围住确切后代，原请求回执仍可读。正向验证组运行与生产发布资格需要实际 Testing Guard。
- CLI、HTTP 和浏览器帧的受控解析专项覆盖输出上限、JSON 类型与缺失、顺序、nonce、作用域、证据缺项及真实退出要求。断言实际文本可保留摘要。专项使用确定输入，独立执行和实际浏览器帧传输另验。
- 隔离 Chrome 命令为 tools/verify-v20-command-recovery.py --probe testing-plan-editor。实际 SPA 构建和 360／1280／1920 布局、三次草稿写入及一次封存通过。浏览器业务响应为夹具，Chrome 及自有 Job 已回收。
