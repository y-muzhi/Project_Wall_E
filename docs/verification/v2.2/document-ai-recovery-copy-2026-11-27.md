# V2.2 文档 AI 恢复副本核对

2026-11-27（香港时间）。独立检出 `.tmp/v22-document-ai`，基线 `990ed2d` 叠加当前候选代码。新增开发环境专用跨结构恢复参数，要求备份资产、已确认的维护引用、原状态和目标固定程序及 Schema 摘要匹配。普通恢复沿用原回执。文档 AI 恢复产生单独的回执和复核结果，旧版部署选择继续拒绝该结果。

- Windows 使用 `tools/python-v20.py -m pytest -q -p no:cacheprovider backend/tests/infrastructure/test_v22_candidate_schema.py` 和自动清理的 `--basetemp`。两项通过，复核保留行的类型摘要，变更数据会拒绝重开。四个改动文件的 Ruff 格式及 `git diff --check` 通过。
- Mac Linux 通过固定 SSH 主机身份，在隔离临时目录复制原开发库的 SQLite 只读快照。使用固定 SQLite 3.54.1 执行 `archived_document_ai_source`、`prepare_document_ai_target`、`reopen_document_ai_target`。第一次转换以及使用同一操作 ID 重试均通过。原快照摘要、人工草稿数量保持一致。单独写入测试计数后，目标核验因保留行摘要改变而拒绝。
- Mac 用例覆盖恢复组件的数据库转换、重放和拒绝，未通过在途开发服务执行正式停写捕获、审计资产收集、回执发布、候选选择、网关切换或开放。源使用只读连接，临时库及临时源码已清理。未提交、未推送、未发计数或模型请求，服务未切换。
