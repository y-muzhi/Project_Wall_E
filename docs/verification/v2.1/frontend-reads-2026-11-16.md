# V2.1前端读取契约与状态（2026-11-16）

环境：隔离工作区codex/v2.1-design-review，HEAD a0f4059＋本轮未提交代码；Node24.15、项目锁定依赖，后端固定SQLite3.54.1。无用户服务更新、正常库修改、真实模型／计数或Git提交推送。

实现：
- api/client复用原transport，单独注册Formation GET与无幂等key的只读POST Preview；不放宽旧分页。新分页支持1—100和不透明字符串游标，读失败保持mutation=false。
- formation-values／formation-reads／formation-errors严格解码Summary、步骤、问题、支线、成果、关系、范围及替代链，检查身份／F／分页／过滤、公开字段及安全错误；首屏total大于items必须有后页。原requirements GET仅在真实返回时保留formation_summary，不为旧后端伪造exists=false。
- WalleApi接入真实读取方法及原DetailReadScope；FormationReadOwner固定需求／文档，分离当前选择和服务焦点，按代次与请求序号丢弃迟到结果；无头部不请求实体页，PATH_CHANGED只自动重读一次，保留明确选择。刷新失败保留上次数据并显示错误，dispose只取消自己的只读请求；不操作IndexedDB、提交正文、生成幂等key或触发AI。
- 初次状态专项发现“摘要失败后详情持续LOADING”和“详情失败刷新仍返回true”，已修正实际catch／返回路径；9项重跑全通过。接口专项初次发现首屏总数／has_more一致性缺失，已补实际解码约束。

检查：接口契约9项＋读取状态9项通过；完整npm test为594 passed、0 failed（6.25秒）。npm run typecheck、npm run format:check通过，npm run build通过（构建1.11秒，另含类型阶段）。既有大chunk提示保留，没有为消除提示改变分包。backend/app Ruff格式560文件通过，formation源码及专项F规则检查通过，git diff --check通过；cleanup-test-artifacts.py --dry-run为JSON=0、screenshots=0。

Preview共享正文匹配函数后补跑test_content_change_on_completed_step_keeps_immutable_closure_and_completion：1 passed，8.92秒，真实含关联的结束／正文更新保留原Closure；不是供应方调用。

未覆盖：本单元是前端读取基础及owner，尚未挂载产品页面；未完成原生命令编辑／确认、提案页、完整预览UI、IndexedDB2／记录5升级及浏览器交互、布局／按钮／空态验收。新AI发布／CARD_RESPONSE与生产Schema210注册仍未完成。构建成功不代表V2.1页面已可用。跨语言实际响应2项通过；后续历史完整读取及最终607项／当前跨端结果见[历史读取证据](frontend-history-2026-11-16.md)。前述594是本子批时点，不冒充最终全量。
