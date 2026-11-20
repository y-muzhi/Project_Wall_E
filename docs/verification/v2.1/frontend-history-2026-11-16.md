# V2.1前端历史读取与跨端契约（2026-11-16）

范围：隔离工作区、HEAD a0f4059＋本轮代码，core/db20-r52、Schema210/db21-r3。现行pending前后端0.1-draft-4原字节／哈希不变。无真实模型／计数、用户服务／正常库修改或Git提交推送。

formation-history.ts及WalleApi接入EVENTS、CHANGES、MEMBERS、CLOSURE、EVIDENCE五类真实路径：
- 事件保留当时VersionBasis、批次／ordinal、固定upper_event_id与Closure；不上传known_f、不用当前F否定历史。
- 13类严格标量快照、11类成员集合分别解码，私有binding不进入公开数据；PROPOSAL_CHECK／ARTIFACT_REVIEW仅允许追加后的事实。
- Closure按RESULT／ISSUE／BRANCH分区取当前页，实际总数与头部一致；证据保留原Revision、范围、来源和摘要。非结果证据只接受SOURCE；不从当前lineage拼接旧事实。
- 复用原transport／安全错误、同一个分页一致性函数及DetailReadScope。历史与当前查询均先冻结原始过滤／游标，再进入写入屏障或等待网络，防止调用方随后修改对象导致请求身份、解码依据不一致。无自动拉全量、本地切页、幂等key或写操作。

专项：formation-history.test.mjs 13项通过，包含13型／11集合逐型正反例、私有字段、错归属／事件／ordinal、页总数、高水位／顺序、原游标字节、历史不接收F、旧Revision、append-only约束及写屏障期间查询被修改。最新完整npm test为607 passed、0 failed（7.25秒）；npm run format:check通过；npm run build含tsc --noEmit通过，Vite 0.787秒，既有大chunk提示保留。前端新增专项总31项（接口9＋owner9＋历史13）。

真实跨端证据：test_v21_frontend_reads.py 2 passed（14.49秒），内部覆盖未初始化、真实人工关联、已结束、结束后正文变更四阶段。通过隔离FastAPI TestClient取得实际HTTP信封，在内存传给Node probe，再经原ApiClient→WalleApi→FormationReadOwner；含当前列表／详情／六关系／ORIGIN及CURRENT范围翻页／lineage、事件／changes／members、三类Closure页及结果证据。正文变更后当前成果NEEDS_REVIEW，原Closure的ARTIFACT证据仍CURRENT。读取前后完整业务／序列快照一致，0新增GuideRun／LLMUse，不落JSON。

首轮受限运行环境90秒超时，未作为通过；本机同一隔离离线检查11.02秒通过，增加Closure后12.58秒通过，补changes／members后15.14秒通过，最终当前源码14.49秒通过。没有用Mock DTO替代后端信封。保留Starlette的既有httpx弃用警告，不为消除警告升级依赖。

当前backend/app Ruff格式560文件、formation源码／专项F规则和git diff --check通过；cleanup-test-artifacts.py --dry-run为JSON=0、screenshots=0。最终本机复核会话均退出0，首轮受限超时保持原结论；只读进程清单未发现本轮probe遗留进程，临时数据库及原始响应不留存。7份本轮文档链接均有效，pending前后端基线哈希不变。

未覆盖：正向非空AI评估／建议／新用途提案、连续AI替代链、1001历史成员跨端大负载仍需对应实际发布链／负载专项；本次source快照纯解码正例不冒充AI执行证据。历史UI、按钮／空态／浏览器、同账本DB2／记录5升级、新AI资源／发布、CARD_RESPONSE及生产显式升级／注册仍待。原启动入口保持Schema200；本轮没有可供用户启用的完整V2.1服务。
