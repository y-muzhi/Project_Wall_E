# V2.0 独立测试计划与人工版本生命周期

2026-11-10，master 28a7c9e 工作区增量。正式 BE OBJ-TEST-PLAN／APP-TEST-PLAN、API06—14 和 FE BND-TEST-PLANS。Schema200 当前不可变资源 db20-r35，manifest SHA256 5f537dac8362de279cd05359c8cbf74c998990e0f3a8215bf08692103122637f，既有 Schema 业务结构及前序包不覆盖。

- `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/test_testing_plan_api.py backend/tests/test_testing_policy_api.py backend/tests/infrastructure/test_v20_command_http.py backend/tests/infrastructure/test_v20_check_case_pack.py backend/tests/infrastructure/test_v20_published_schema.py backend/tests/infrastructure/test_v20_schema_graph.py`，50 项通过（88.79 秒）。使用隔离真实服务 ASGI、Schema200、V1.5 原文编辑／确认事实与现行 CHECK20。覆盖计划身份、版本／过滤／越界、原键重放、固定主 Revision 与材料和引用原文、未确认发布拒绝、同版本草稿 CAS、人工发布／撤销独立资源审计、不可改写历史、非法脚本和空步骤。未发布的独立编译能力阻止任何 AUTO 包落地。首次专项测试夹具误用了文档元数据版本 2，修为实际的 1 后通过。
- 计划创建／草稿／发布／撤销不创建 CodingTask、TestingTask 或模型调用。发布和撤销在同事务记录 TEST_PLAN_VERSION 资源操作及两步，原已回执可重读原版本；同版本保存不得改绑主文档／Revision 或材料。改依据时另建版本。
- /testing/plans 已接计划身份创建、目录及固定版本读回、明确发布和带原因撤销；后端负责重新核对原确认、范围和版本。隔离 Chrome 360／1024／1280／1920 扩展专项已通过，覆盖目录空态、创建且选中、固定原文、取消发布、人工发布、撤销响应丢失后核对原回执、跨计划及缺祖先 ID 拒绝。早次发现设置入口将点击事件误作计划 ID，修正为显式无参数导航后通过。网页结构化草稿编辑器、自动用例可编译准入、测试包、参考集与执行链仍待续。
- 前端最新 TypeScript、Prettier、566 项 Node 测试及隔离浏览器构建通过；Python Ruff 格式（395 文件）、受影响模块 lint、Git diff 空白和清单内源／字节／SHA-256 校验通过。既有 CRLF 转换提示仍由 Git 如实输出。

- 最终 Testing 浏览器重跑通过，计划名称接受 200 个非 BMP Unicode 码点并拒绝 201 个；未额外发送验证请求。另运行 `tools/verify-v20-command-recovery.py --probe settings`，现有 Coding 设置在 360／1280 通过，覆盖原登记、读取、同键恢复、撤销原请求、配置版本及授权。两个浏览器 Job 均完成回收，临时输出已清理。
