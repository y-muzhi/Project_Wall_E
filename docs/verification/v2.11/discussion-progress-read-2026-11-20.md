# V2.11 讨论进展读取检查（2026-11-20）

- 现场只读核对：Windows，当前工作区 `a0f4059`；5174 代理原 8001。`GET /api/v1/requirements/2?expand=discussion&document_id=2` 返回 200，讨论版本为 3，主题为 0，且有 `formation_summary`；需求级扩展返回没有该字段。原精确解码拒绝新增字段。首次读取审批 403 后重试成功。
- 离线回归：`node --test --test-name-pattern 'document progress reads' tests/v15-reading.test.mjs` 在修复前复现读取失败。修复后在 `frontend/` 运行 `node --test tests/v15-reading.test.mjs tests/v15-discussion.test.mjs tests/v15-discussion-presentation.test.mjs tests/api-models.test.mjs tests/api-bindings.test.mjs`，39 项通过。包括带与不带摘要、拒绝损坏核心及未识别字段、保留已加载的讨论、重试恢复。
- 静态核对：`npm run format:check`、`npm run typecheck` 通过。
- 在线只读核对：通过 5174 请求 `/src/api/models.ts`，确认实际返回本次修改及 `requirementDetail` 导出。浏览器打开 `/requirements/2` 并点击「进展」，显示「暂无讨论主题」，错误提示不再出现。正常已有主题与失败重试未在真实页面制造数据或故障。未触发模型、计数或写入，5174／94200 和 8001／58436 均未重启。
