# V1.5固定目标候选及请求详情检查

2026-10-22；工作区未提交。环境Windows／项目.venv／Node；所有SQLite及count journal使用TemporaryDirectory清理。只保存本Markdown，不留JSON、原始日志或浏览器产物。

- `python -m pytest backend/tests/suggestions/test_v15_batches.py -q -p no:cacheprovider -x`：初建5项最终38.25秒通过；覆盖目标B而来源A不变、EDITED／REJECTED、NO_CHANGE不增CONTENT、放弃保留决定、版本拒绝、审计写失败全事务回滚及原键重放、实际HTTP契约。初始夹具缺SourceRef.block_ids、误把完整隐式来源当只含手动项，已按正式规则修正；不放宽程序来源校验。
- 同轮阶段卡片新主题／依据／成果映射正向1项已通过；初始断言错误读取当前phase未决项及不存在的detail_json列，改为真实PHASE_CHANGED.payload_json.phase_before.closure，与产品保存规则一致。
- `python -m pytest backend/tests/guide/test_v15_model_calls.py -q -p no:cacheprovider -x`：2 passed／20.18秒，真实保存调用后按8分区／8项计数、预算、选择清单及HTTP读取；direct GET禁socket及编译，事实计数不变。Windows TestClient初始化自身本地self-pipe需要socket，HTTP阶段恢复此函数，保留禁止上下文编译；未开放真实供应方。夹具分区清单排除非分区schema_version。
- 前端model-calls及suggestion-batch共20 passed／291.34毫秒；追加composer／cards／comment共35 passed／367.83毫秒，涵盖阅读另一同版本文档仍按固定批次目标提交、未知原请求恢复及确定后仅读。类型检查此前通过；最新完整类型／临时生产构建正在执行。
- 新增表格采用专项及后端联合仍在执行，不提前写通过。没有真实模型／计数API、用户数据库写入、服务启停或Git写入；尚无浏览器、供应方或全版验收证据。
