# 建议批量接受与审阅层级专项检查

2026-10-27，M15-SUGGEST-01。以master／48fab5b之后的工作区增量实施，保留此前来源恢复及评论范围未提交修改。用户授权批量接受及内容／操作层级优化；执行相关离线、类型、临时生产构建与隔离浏览器。真实供应方0、用户正文0写入、Git未写；服务加载尚未执行，待本轮许可。

## 实际范围与设计

新增APP-BATCH-CMD-C04／BND-BATCH-API-I42：POST suggestion-batches/{id}/accept-pending，冻结expected_content_version及完整有序expected_pending_ids（唯一1—100项）和原key。复用原真实批次占用／固定目标／Scope授权／原文与补丁验证，先验全部再同事务接受全部PENDING；任一失败无部分决定。非目标ACCEPTED／REJECTED／EDITED不由本次操作改动，无新实体、模型调用或正文版本；完成本批仍独立确认。并发非目标决定合法变化以实际事实展示，不永久卡住原回执恢复。

前端原owner新ACCEPT_PENDING意图，原ApiAction保存body/key，UNKNOWN及已确认后读取失败分别恢复；回执检查固定批次／不可变候选／实际接受集合，正常一次提交、一次统一核对，不逐项循环写入／刷新。未保存待处理编辑禁用批量，明确取消才清理草稿；确认弹窗冻结集合，取消0提交。

审阅四层：批次目标／统计／状态→折叠说明与来源＋工具栏→独立建议卡片与原文／建议对照→单项操作栏和固定批次操作区。>=640px面板双列，否则上下；长内容内滚动，表格原编辑与预览复用；状态、内容、动作不再混排。

正式FE／BE保持1.0／EFFECTIVE。FE前a8cc0e8fb14aae99d379969b314b4772a99cac5eabae6b99bae4bd82fa2d5a6c，后d93de1cdcb0085bea251a6be933d8fb843dc04bec269e89d02f9b98faadc500b；BE前92f7798339f0c12b403b803682dc7bf7255e46e252b707a6759b68df0bb00f28，后fc34481af473ea40617cd859329f07aa03147c19d983f3f700c1b6a9ea02359d。12个本专项实现／检查／离线工具文件按排序路径、NUL、原字节、NUL聚合SHA256=dc891a1f16ed84c6a5b0f36528a82cc8fefc61d4fc9ca54a1caa97a218e9fb1a。完整文件集合为suggestions后端api／contracts／commands／http_models、前端WalleApi及suggestions批次owner／panel／panel.css、两前端专项／新后端bulk专项、serve-v15-offline.py；未改模型可见协议或冻结资源。

## 离线、HTTP与构建

- `.venv/Scripts/python.exe -m pytest backend/tests/suggestions/test_v15_bulk_accept.py backend/tests/suggestions/test_v15_batches.py -q -p no:cacheprovider --tb=short`：实际用TemporaryDirectory包裹pytest.main、tempfile.tempdir指向本轮工作区独占根，12 passed／72.76秒。新增合法并发非目标决定1项后，仅跑`-k concurrent_nonpending`，1 passed／20.56秒，共13项适用通过，不冒称单次13项记录。7项bulk覆盖既有决定保留、原key重放／改集合拒绝、版本／排序／外来及陈旧集合、全验证先于写入、第二次仓储失败整事务回滚、严格HTTP与合法并发；原6项继续覆盖最终目标应用及原决定／丢弃。
- 后端首轮4通过2失败／41.98秒：故障夹具曾试图直接改不可变候选被IMMUTABLE_FIELD阻止，改为明确私有验证失败注入，未删除触发器；新请求未声明body_fields导致被按空请求体解析，已修实际适配器。没有通过放宽保护让检查通过。既有Starlette弃用提示保持。
- 前端相关owner／展示23 passed／2045.9841ms；新增4项bulk覆盖单次动作／单次统一读、UNKNOWN精确重放、确认后仅读、未保存编辑、冻结确认集合与互斥、伪回执及合法非目标变化。API绑定补I42／1次请求路径参数，路由计数42／客户端39；首轮旧41／38断言失败，已与实际新接口同步。
- 最终`npm.cmd test`403 passed／4361.4196ms；`npm.cmd run typecheck`退出0。
- `node node_modules/vite/bin/vite.js build --outDir ../walle-v15-browser-lcmh733m/frontend --emptyOutDir --logLevel warn`退出0，仅既有500kB chunk提示；输出仅临时站点目录，未覆盖frontend/dist。新输入补明确aria-label，最后仅细化批量UNKNOWN文案后执行上述最终全量／类型／构建，不增加付费测试。

## 实际隔离页面

使用playwright技能、tools/serve-v15-offline.py --serve真实应用／SQLite／Worker；站点PID42020／PTY63305／63443，临时根walle-v15-browser-lcmh733m；命名浏览器walle-bulk-review。工具仅在私有[bulk-review]夹具生成15段及15项真实建议，不向产品开放模式；通过该独占站点API建立资料，2批Counter／2次Gateway，真实供应方0。

1. 实际打开15项候选。1600×1000、窄面板约420／514px：原文建议上下，工具栏可换行；2048×1100、面板962px：两列445／445px。三份代表临时截图已查看，无页面横向溢出；固定底部操作与独立列表滚动均可达，来源说明折叠。
2. 在真实列表拒绝第1项；编辑第2项为“第二项：保留用户编辑的推荐说明。”并保存接受，统计为待处理13／拒绝1／编辑1。编辑期间批量禁用、就地原因可见；另开第3项未保存编辑后取消，批量恢复可用且无单条写入。
3. 13项批量确认显示冻结数量、保留已有决定／正文不变；Esc取消后后端C04幂等记录仍0，模型调用仍2。
4. 正式确认后故意丢弃一次已成功回执。页面UNKNOWN保留原动作，不因GET实际已接受就认领成功。按“重新确认结果”恢复，实际两次请求body和Idempotency-Key均相同；服务端C04成功记录仅1，计数为接受13／拒绝1／编辑1，用户编辑仍精确保留。没有逐项提交13次；正文仍V1、Chat仍2。
5. 独立“完成本批修改→确认应用”后仅V1→V2，拒绝项原来源文字与用户编辑保留，批次真实已应用、alerts空、无横向溢出、Chat仍2。

初始页面尚在读取时一次find未命中；一处自动化精确字段名曾包含标签帮助文导致定位超时，未重复提交前一个决定，已改显式aria-label并用实际字段继续。故意丢回执产生一条预期网络错误，不把该浏览器全程记为console零错。最后文案调整后的构建完成；最终重开只做初始只读状态及关闭，没有重跑整条业务，不额外宣称一次新全流程。

## 清理与用户现场

浏览器已close，PTY63305 stop退出0，报告Counter2批／Gateway2次与自动清理完成；临时根不存在、63443无监听，walle-bulk-tests-*不存在。cleanup-test-artifacts.py --dry-run：JSON0／截图0，不保留截图、快照、录像、HAR或原始日志；正式配置／输入／用户库未清理。

用户只读核实8000／PID41388／PTY8803与5173／PID12440仍运行；1个需求IDLE、1个SUGGESTION_REVIEWING、1个PENDING批次，RUNNING AI／EDITING人工／PROCESSING幂等提交均0。原待审阅批次保留，未代点任何决定；本次不因代码完成自动重启，不能复用上次评论范围重启许可。

未覆盖：真实模型新效果、专门表格行浏览器全链、其他浏览器／高倍缩放／跨标签完整组合。表格行与原恢复／权限由相关离线回归承接。整版原人工语义验收不因本专项改变。当前UI源码可能被Vite更新，8000新批量API尚未加载，加载前不称用户新操作已可用；后续明确服务许可及只读结果另补记。

## 静态收尾

2026-10-27：23份变动Markdown的380个本地文件链接均存在；git diff --check退出0。后端设计原代码围栏及引用原文与HEAD一致，backend/resources无差异；独占测试根均不存在，清理dry-run为JSON0／截图0。当前代码及必要验证已完成，等待本任务新的用户服务加载许可，不复用历史许可。

## 本轮获准用户服务加载

2026-10-27用户明确答复“允许重启后端加载功能”。先只读核对8000／41388、5173／12440及RUNNING GuideRun／EDITING人工／PROCESSING提交均0；原批次2为PENDING，共15项，已接受1、待处理14。保留待审阅批次，不要求用户先处理或丢弃。

旧PTY8803 Ctrl+C正常完成Application shutdown complete／Finished server process，Windows控制台退出1，8000端口已释放。沿原绝对WALLE_DATABASE_PATH与tools/ai-service.py --start --credential-file绝对.env.local安全助手启动新PID47020／PTY84129，Application startup complete，8000监听；5173／12440保持。不初始化、迁移或再导入准入，不打印凭据，无模型或计数调用。

仅9项GET：8000需求2（expand=discussion）、批次2、CURRENT（document_id=2）、评论及comment-index，5173需求页、suggestions/panel.tsx、api/walle.ts、suggestions/panel.css均200；实际前端模块包含“接受全部待处理”、accept-pending绑定及review-diff样式。未发送POST／PUT或代点用户批量按钮，批量动作功能证据仍为前述隔离流程。

重启前后对requirements、suggestion_batches、suggestions、requirement_documents、revisions、guide_runs、llm_uses、comments、idempotency_records九类业务表全部行按固定顺序JSON序列化并在内存中计算SHA256，数量及摘要逐项一致；不保存原始内容／JSON。原批次仍15项／已接受1／待处理14；GuideRun17、LLMUse17、Comment4及三类在途0保持。新服务正常运行，用户可刷新http://127.0.0.1:5173/requirements进入新审阅界面。此前“未加载／待许可”段落是授权前现场，本节为最终状态。
