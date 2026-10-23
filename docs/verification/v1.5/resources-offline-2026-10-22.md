# V1.5 资源离线专项

- 日期：2026-10-22（Asia/Hong_Kong）。工作区未提交；保留此前文档整理改动。
- 范围：B1资源完整单元，新增backend/resources/v9、现有ResourceCatalog入口、Schema命名闭包及声明顺序序列化。未接入V1.5运行接受／调度链，不能据此宣布整版可用。
- 环境：项目`.venv`现有Python及锁定依赖；未访问环境密钥、业务库、服务或真实供应方。
- 生成：`.\.venv\Scripts\python.exe tools/build-collaboration-resources.py`。生成21个正式资源及manifest；生成器拒绝覆盖目录。首次生成前Release校验发现reserve未设固定1024，修复生成器后成功；该失败未创建资源目录。
- Manifest SHA-256：`daf7ee47c3d4aab4e186f29c195be10e6e17795db5299dae9b3727cedd93ce8c`。
- Release SHA-256：`dd1509adea77f7fdb225ba0664e7c01342105a0391be4512498aa3f396759710`，明确OFFLINE_READY；没有真实观测证据，不放行普通Chat。
- 命令：`.\.venv\Scripts\python.exe -m pytest backend/tests/infrastructure/test_collaboration_resources.py backend/tests/infrastructure/test_schema_transport.py backend/tests/infrastructure/test_versioned_resources.py -q -p no:cacheprovider`。
- 实际结果：28 passed，31 subtests passed，23.10秒。覆盖正式源内容一致、全部89类型的本地最小闭包、四阶段×六任务确定system、任务输出互斥、未知字段／缺失nullable／布尔整数／非法Unicode拒绝、声明顺序、摘要及修改防护、OFFLINE_READY／profile阻断、原资源回归。
- 测试临时目录使用TemporaryDirectory成功／失败清理；不产生测试JSON、截图、录像或原始日志。资源JSON为正式输入，应保留。
- 未覆盖：实际材料选取／Wire投影、计数调度、最终调用审计与业务保存、HTTP和前端接入、浏览器、真实Tokenization／Chat及模型效果。生产LIVE_VERIFIED需要后续明确授权及实际证据。
