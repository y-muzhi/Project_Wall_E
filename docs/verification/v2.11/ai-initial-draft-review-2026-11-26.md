# V2.11 AI 初稿审阅边界上线验证

2026-11-26（香港时间）。依据[独立迭代](../../iterations/pending/v2.11/WALL-E.AI初稿审阅边界迭代_V_2.11.md)，本地工作树 `codex/v211-receipt-followup`，基线 `fd484f4`。

| 层次 | 实际结果 |
| --- | --- |
| 后端离线 | 固定 SQLite、隔离数据库与模拟供应方。运行 `test_openai_writes.py` 和 `test_v211_document_types.py`，14 项通过。固定模板 V1 的第一章先形成待审批次，当前正式修订不动。接受组时仍为 V1，确认应用后生成 V2，下一章原文保留。原始空白写入、新建、明确仅提建议、模板恢复、过期与超时回归通过。 |
| 前端 | 格式、严格类型、生产构建和 656 项离线检查通过。旧文案断言更新为新规则后复跑通过。 |
| 服务 | 5197 临时启动及历史回执 GET 通过，切换前已退出。8001 原 PID 45120，现 PID 51052。复核时无在途 AI、代码或测试任务，有 2 批待审。使用原 Schema210 审阅库和计数审计路径。 |
| 线上只读 | 实际页面的修订范围已显示「已有正文先生成待审阅建议。原始空白文档的首份正文可直接保存。」历史运行 53 仍指向原正式修订 ID 22。浏览器写请求和页面错误均为零，未调用真实模型或计数。 |

发布目录位于 `data/service-runtime-v211-review-20261125`。后端源码为 `source-initial-review-20261126`，启动沿用同目录 `store/walle.sqlite`、原本地凭据与 7890 代理、`db21-document-review-r1`、讨论 `openai-v6` 和文档 `openai-v8`。静态前端沿用 `frontend-final`，主资源为 `assets/index-D944XA8F.js`，HTML SHA-256 为 `358dda21cde5ebb3884a256fef51ed661c9e2f13e5b343284300d54f42b6e865`。回退源为 `source-7059587`，旧静态入口保存在 `frontend-initial-review-2026-11-26/previous-index.html`。
