# V2.0原键接收、关闭及回执（持续实施）

日期：2026-11-04；HEAD 28a7c9e，V2源码未提交。真实服务未启动／更新，正常业务数据、模型及计数API均未访问。

依据：BE 2.2、6.1、APP-COMMAND-CLOSE、APP-CODE-QUERY的CommandReceiptLookup、API-CODE-31／70及API-TEST-43、7.1.7；此单元完整阅读。客户端IDB及全部业务入口尚待实现，不宣称整版命令闭环。

实现：
- 原Idempotency.execute对注册CODE／TEST scope走同短事务claim＋实际同步结果／Operation接收；直接孤立claim禁止。其他文档原路径保留。原键CLOSED先于输入指纹比较；不同输入OPERATION_CONFLICT；原成功／确定拒绝只重放。
- command_receipts.py复用同idempotency_records，关闭整个原键，无body、不递归scope。关闭先提交则禁止迟到执行；已接收只返回ALREADY_RECEIVED，不取消外部活动。可靠提交后才返回关闭成功。异步接受要求真实同原键Operation，模块／owner不混用。
- PROCESSING未知保留：启动清理排除Coding／Testing；abandon禁止，新增数据库DELETE保护。只有旧文档PROCESSING按原启动规则清理。未知claim读取UNKNOWN／PROCESSING且不伪造关联。
- command_api.py的3个真实接口接入service.py：POST /command-intents/close；GET /code-command-receipts及/testing-command-receipts。严格注册、路径／键／跨模块／未知字段／重复参数校验；GET不接收幂等头。
- shared/http_errors、http_boundary增加显式V2错误契约，原响应壳和文档错误形状保留；V2错误明细严格Input／Conflict／Authorization／Readiness／Closed结构。存储未知503不伪装NOT_FOUND。LeasedDatabase传递真实schema_release，退休后关闭仍不可晚提交。
- 默认151服务不自动初始化／升级200；新控制接口返回503 DATABASE，原文档接口仍正常。Schema200 release pin及正式启动选择待P1后续维护完成。

本轮实际检查：
1. 固定SQLite启动器＋tools/quality_python.py，test_v20_command_receipts：9通过（6.53秒），真实文件SQLite／两连接接收与关闭交错、关闭后迟到／不同body、原错误、未知清理、遗失提交回执、真实Operation同事务。
2. 最后组合：test_v20_command_http、test_v20_command_receipts、shared/test_http_errors、infrastructure/test_idempotency、test_execution_lease、test_v15_service_foundation：37通过、30子场景通过（46.57秒）。实际生产factory在进程内创建，未监听端口或启停用户服务；HTTP测试含新request_id、跨模块、原成功／403拒绝回执、原正文不泄露、读取故障503、lease退场、151边界。网络／正常库／凭据访问保护开启。
3. 扩大检查首次10失败来自旧低层测试复用1.0字段initialization_mode及旧创建流程；新增fixtures_v151用现行RequirementRepository／MessageRepository，调整受影响idempotency／crash_worker／lease夹具，保留原断言和真实崩溃／事务检查。未修改冻结旧Schema迎合测试，未批量改其他历史业务专项。修复后上述组合通过。
4. 后端145文件格式及git diff --check通过。各次组合分别记录，不把历史结果当新完整回归。既有Starlette弃用提示保留，未更新依赖。

当前继续项：确定4xx在业务写入后可靠回滚时的原claim保留分支仍需受控保存点支持和专项；当前回调必须先完成确定拒绝校验再写入，写后拒绝会整事务回滚，不伪存终局。随后接客户端严格decoder／原键控制，并完成Schema200发布／维护工具。未覆盖实际模型、Git／Windows／OpenCode、IDB跨标签页、页面交互及产品验收。临时数据和原始日志未留存。

后续完成：写后确定拒绝的受控保存点／原claim分支及14项核心专项已实现；最新13文件87通过／47子场景，见[audit-owners-and-rejection-2026-11-04.md](audit-owners-and-rejection-2026-11-04.md)。本文件上方“仍需受控保存点”是被本补充替代的接续状态，非当前缺口。
