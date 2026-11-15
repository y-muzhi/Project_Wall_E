# V2.0 独立模型审计及运行前置检查

2026-11-10，Asia/Hong_Kong。master 28a7c9e 工作树，Schema200 db20-r36。测试使用隔离 SQLite、ASGI 与独立 Chrome。模型调用记录采用明确账务夹具。

- API41／42 锁定 Python 专项为 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/test_testing_task_api.py。模型记录测试覆盖真实 owner、逐页读取、部分／最终用量、真实 0、原不透明请求 ID、预留／结算及脱敏。夹具初次 SQL 参数数有误，补正后该专项通过。前端隔离 Chrome 测到无调用空态、只读详情、输入 0、输出缺项和待结算。
- API28 核对原任务、版本、固定资产、授权、来源、已有执行及停止状态。未准备或终止的任务拒绝，原 4xx 可查。独立 Driver 未准入时不产生 RUN_TEST、Verification、模型账或报告。封存字节及 Runner／夹具原身份按实际 NTFS 资源复验，损坏分支由包生命周期专项验证。
- 浏览器验证使用 tools/verify-v20-command-recovery.py --probe testing-task-workspace。用量部分实际 SPA、HTTP 夹具，原调用读取不触发任何供应方。Chrome、Job 和临时输出已回收。
- 尚未执行实际 Testing 起草、供应商调用、独立 CHECK_DRIVER 或正式运行环境准入。
