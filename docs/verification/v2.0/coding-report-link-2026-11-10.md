# V2.0 Coding 关联独立报告

2026-11-10，Asia/Hong_Kong。master 28a7c9e 工作树，Schema200 db20-r36。关联使用现有 Coding 任务及原独立 Testing 报告。

- API69 由用户明确选择报告，使用原请求键及任务版本。写事务重验原发布链、当前候选、设计材料、固定资产、独立证据及停止／清理。在提交前持有原参考、Runner／夹具及封存包闭包。通过后保存原两步操作及待接收状态；同报告重新关联保留已有预览，改用另一份报告时需重新预览。
- tools/verify-v20-command-recovery.py --probe coding-report-link 在隔离 Chrome 360 像素通过。实际 SPA 与响应夹具覆盖固定候选和设计预填、默认验收、独立授权门槛、暂无报告、一次关联后响应丢失、同键读回待接收、资产撤销后保留原通过。候选预填查看未写 Testing。首轮发现动作解码、C68 旧回执夹具额外字段及相邻组件重复 React key，已修正；长工作台探针一次到达原 180 秒上限，由自有 Job 回收。只对完整工作台探针提高隔离测试时限后，tools/verify-v20-command-recovery.py --probe tasks 复跑通过，覆盖 360／1280、原发布、候选草稿、报告关联及原有控制回归。两种浏览器探针均清理临时输出。
- TypeScript strict、锁定 Prettier 与 566 项前端回归通过。浏览器独立关联通过路径使用固定 HTTP 夹具。原真实候选关联、最终接收和交付需实际通过的独立 Testing 证据。
- 两次既有 PROJECT_CHECK_HANDOFF 原 Windows Guard 回归在管道读等待超时。放宽该测试场景的单帧等待后，第三次定位为 C69 缺报告分支构造 Rejection 时遗漏 details，导致 500。已修正 C69 与相邻 C68 的相同分支。实际 ASGI／SQLite 专项已确认缺目标返回 404、同键原拒绝可查及重放。第四次 Guard 联合 1 项通过，491.25 秒。已核对原三角色及原投递恢复、已发布候选及同候选复检、C69 可选报告动作和缺报告 404。实际 Windows Guard、认证管道和 Job，OpenCode／模型响应采用隔离夹具。产品运行超时保持原配置。
