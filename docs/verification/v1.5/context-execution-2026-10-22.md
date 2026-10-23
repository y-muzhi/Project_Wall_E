# V1.5上下文及执行专项（2026-10-22）

未提交工作区，Windows、Python .venv。隔离SQLite及进程内实际仓储，所有目录使用TemporaryDirectory清理；未请求真实模型／计数API，未启动或更新服务。正向count／Chat仅私有测试替换，不能视为供应方证据。

- `python -m pytest backend/tests/guide/test_v15_context.py -q -p no:cacheprovider`：最终7 passed，24.20秒。零文档、确定重放、长期pending跨10条、目标／来源去重、局部范围及可选背景、SPEC生成结构、正式答案只传原题／所选标签、版本冲突停止。初次发现Revision字段应映射source_content_version／markdown_snapshot／block_state_snapshot_json，已修正；未改冻结资源。
- `python -m pytest backend/tests/guide/test_v15_counting.py -q -p no:cacheprovider`：5 passed，18.62秒。OFFLINE_READY计数前阻断、恰8项与一次合格即停、3候选顺序、空可选集合跳过、计数失败不重试及实际usage／framing新准入。
- 实际执行专项尚进行中：首轮6项4通过，生成／修订因共享事务保护拒绝SAVEPOINT。已改程序先验证再写，不放宽DB保护；尚待最终重查，不提前记通过。

未覆盖：供应方兼容／模型效果、浏览器、C05／C06全部分派、批次完成与前端请求详情。完整阶段结果后继续追加。

## 单轮执行最终结果

`python -m pytest backend/tests/guide/test_v15_execution.py -q -p no:cacheprovider` 最终10 passed，62.07秒。实际SQLite事务、正常LLMUse和count-journal审计，Chat／Tokenization均为显式私有离线依赖。覆盖新稿V1直接保存、指定目标修订V2、业务CLOSED不取消授权、正文和进度独立处理、坏JSON原文、可重试网络错误只请求一次、取消先提交后迟到usage、存储失败整体回滚而保留真实调用、局部scope外拒绝及原区块身份。

修复：不采用SAVEPOINT放宽共享事务，改纯校验／准备后再调用仓储提交；保留原trusted_output_json仅在validation_status=SUCCEEDED时非空的数据库约束，部分语义失败留原始审计和实际应用结果。重跑前定向生成／修订的中间失败由上述结果替代。后续RUN_MATERIAL及进度扩展仍待联合回归。
