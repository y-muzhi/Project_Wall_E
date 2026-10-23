# V1.5 AI接受与终态基础专项

2026-10-22，未提交工作树；隔离TemporaryDirectory SQLite、真实OS锁和FastAPI TestClient，不启动监听服务。命令：`python -m pytest backend/tests/guide/test_v15_acceptance.py -q -x`，最终10 passed，32.75秒。仅既有Starlette/httpx弃用警告。

已验证：零文档讨论接受、原话与pending、六任务输入边界、生成只接受未建稿、固定目标及只读来源、原键／版本竞争、接受失败全事务回滚、PERSISTING前取消与pending保留、结束父轮创建新DISCUSS、显式失败重试新run并保留原USER输入；HTTP202新RunReceipt与GET实际运行／历史。OFFLINE_READY准入在上下文／计数／网关之前拒绝，FAILED CONFIG_INVALID并释放占用，LLMUse仍0。禁止依赖一旦被调用即抛错，没有真实供应方／计数调用。

尚未覆盖完整Canonical／Wire／8项计数／三批预算／返回持久化、卡片与候选、真实模型效果；前端AI协议未同步。不得将接受成功及准入拒绝表述为完整AI功能可用。RUN_MATERIAL正例与更多阶段／来源边界待实际ContextBasis单元。新GuideRun公共字段及终态应用结果语义在contracts处增量落实，正式设计还需本单元对应细化同步。

所有测试库及锁目录退出清理，没有测试JSON／截图／录像／原始日志；没有用户库、服务或Git写操作。

## 前端接受路径

2026-10-22，未提交工作区：`node --test tests/v15-ai-composer.test.mjs` 7 passed（1860.79毫秒）。覆盖零文档讨论原话、显式目标独立于阅读、新建目标与SECTION规范、UNKNOWN重放原动作、接受后GET失败仅重读、晚到绑定不覆盖用户选择及真实API冻结body／key。`node node_modules/typescript/bin/tsc --noEmit` 完整通过。Vite使用Python TemporaryDirectory作为outDir，1248模块、2.58秒构建通过；仅既有大chunk提示，目录已清理，未覆盖frontend/dist。诊断入口只适配了新接受传输，部分卡片运行期旧预期尚待后续；未执行浏览器，未调用供应方。
