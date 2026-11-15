# V2.0 原验证、测试报告与发现项复核

2026-11-10，Asia/Hong_Kong。工作区 master 28a7c9e，Schema200 db20-r36，隔离 ASGI、SQLite 与真实 NTFS 封存。已持久化运行和用例记录为明确测试夹具；没有使用真实候选执行、用户库或模型。

- tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/test_testing_report_api.py，2 项通过。夹具首轮缺仓库记录、次轮错用对象序列化保存数组，已按生产表及 JSON 形状修复。运行有既有 Starlette TestClient 弃用提示。
- API35／36 按 TestingTask、Verification 和 Item 的真实归属读取，按固定 CasePack 解析计数并隐去实际原值。跨祖先、完整性项冒充用例、未知查询、分页越界分别验证。
- API37／38 同源报告读取，报告的历史结果及输入摘要在包撤销后保持，资格附加资产已撤销的原因。快照报告没有 Coding 交付资格。
- API39／40 检查报告内发现项、保存 CAS 和不可变归因操作。PRODUCT 需受控失败证据和原设计引文。重分类保留首次请求结果，拒绝缺用例与 UNCLASSIFIED。归因不修改报告。
- 前端 strict 类型和锁定 Prettier 已通过。tools/verify-v20-command-recovery.py --probe testing-task-workspace 在隔离 Chrome 360／1024／1280／1920 通过，涵盖失败与空态、归因草稿刷新、丢失响应后的原键恢复、撤销后资格变化与原验证及用例展开。实际 SPA，HTTP 用固定夹具。一次归因 POST，无 Coding 写入；Chrome、Job 和临时输出已清理。实际 Testing 生成报告及真实 Coding 报告接收另验。
