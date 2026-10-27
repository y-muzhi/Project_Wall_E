# 评论建议来源复用修复检查

2026-10-26，M15-COMMENT-01，源码／授权离线检查及用户批准的后端加载均完成。用户报告单条评论AI建议入口报SOURCE_INVALID。本轮代码／必要离线检查及文档；不实现批量评论，不调用真实模型或计数，不写用户业务记录，服务更新仅按后续明确授权执行，不做Git写操作。初始HEAD48fab5b，工作区干净。

## 原因与复现

只读mode=ro检查正常库：一轮评论产生的实际SourceRef使用material_ref=comment_anchor，同次ContextBasis.selected.ref为r15:comment_anchor，selected.source_refs保留原始SourceRef。后续讨论依据合法引用该材料，原verify_source_refs及capture_source却只按selected.ref等于material_ref查找，分别只读复现SOURCE_INVALID。只记录安全身份和结果，不复制用户评论／模型原文或私有错误体。

新增隔离真实SQLite／HTTP回归，先执行评论建议并用私有Gateway返回候选及带当前用户消息＋评论材料的合法进度，释放候选占用，再发下一评论／普通讨论。修复前两个变体均在材料核实处失败（2 failed／25.33秒）；未修改用户数据或触发真实调用。

## 实现与已完成检查

requirements/source_refs.saved_run_material复用原模块，按严格Schema、同需求run、selected.ref或该RUN_MATERIAL.selected.source_refs真实完整映射核实，唯一且alias来源一致；verify_source_refs与guide/accepted_context.capture_source共用。原Wire摘要、严格解码及已携带材料范围保护保留，不猜前后缀／新别名、不改库或历史数据。未新增SourceRef种类、业务实体、HTTP字段／服务、Schema或资源批次。前端两处入口文案同步既有设计“根据评论提出修改建议”，不承诺直接覆盖正文。

- 修复后最初2项复现25.26秒通过；加入负向边界后整个test_v15_comment_guides.py 7 passed／47.09秒，1条既有Starlette弃用提示。覆盖后续真实202、上下文编译、原快照未变、同需求／错run／不猜ref、selected缺失／歧义、alias冲突及外来Basis拒绝，保留旧评论变动后重试拒绝。私有Counter／Gateway，无真实供应方。
- 再次mode=ro对原run15材料执行来源核实及捕获均成功，正常保存快照前后相同；没有向正常服务提交评论命令、建立新run或调用供应方。
- 前端4个现有评论专项26 passed／2054.0823ms；原请求／UNKNOWN／目标版本／列表与锚点边界保持。
- 前端tsc退出0；Vite临时生产构建退出0，仅既有500kB chunk提醒。临时目录由TemporaryDirectory成功／失败均清理，frontend/dist未覆盖。

扩大相关后端6文件最终63 passed／287.10秒，1条既有Starlette弃用提示；与评论7项合计70项通过，未机械重跑全后端。命令为`python -m pytest backend/tests/requirements/test_v15_discussion.py backend/tests/guide/test_v15_acceptance.py backend/tests/guide/test_v15_context.py backend/tests/guide/test_v15_cards.py backend/tests/guide/test_v15_execution.py backend/tests/comments/test_v15_comments.py -q -p no:cacheprovider --tb=short`。源码与正式BE OBJ-REQ来源语义同步；完整模型Prompt／Schema和冻结资源未改。加载许可取得前阶段：用户后端8000／PID15852、前端5173／PID12440仍运行，未启停；当时后端未自动加载Python修复，后续许可与实际加载见下节。无本轮浏览器或真实效果验证，不复用历史真实许可。


在显式只读BEGIN事务中，对现有未解决评论ID3／4使用真实评论、target、scope及实际讨论依据执行capture_inputs均通过，total_changes=0，未调用写命令、建立run或发送任何供应方请求。首次脚本没显式BEGIN，被DocumentSources的共享事务保护拒绝；改为只读事务后通过，保护保留。

受影响Python语法解析通过。v15 manifest／release与Git HEAD逐字节一致，正式BE的15段代码围栏／引用Prompt聚合仍d9fcf952ab6721516a32f85e5494f565fcb8fa950e8689cd587db8f7a069a52d。服务更新许可尚未取得，未重新请求原用户评论；未执行真实模型效果或额外浏览器新验收。最终静态检查另补于下。


## 后续授权加载（2026-10-26）

用户已明确选择“允许重启后端加载修复”。执行前只读核实全部需求无活动占用、RUNNING GuideRun0、EDITING人工会话0、PENDING候选0；核实原8000／PID15852为既有安全助手服务、前端5173／PID12440保持。向原PTY80858发送Ctrl+C，已输出Shutting down／Application shutdown complete／Finished server process15852；Windows控制台退出码1，实际生命周期正常关闭，8000释放，未强杀其他进程。

以原现有data/wall-e-v1.5.sqlite设置绝对WALLE_DATABASE_PATH，原tools/ai-service.py --start --credential-file绝对.env.local安全加载，schema／原v15准入检查通过，无初始化／迁移／导入准入或供应方调用。新后端8000／PID13012／PTY22018，Application startup complete，保持运行；前端5173／PID12440不重启。密钥仅由原助手读取，不输出或记录。

重启后只读GET需求2含discussion、当前评论列表和索引、5173需求页及comments/panel模块均200，模块含“根据评论提出修改建议”；正常库仍无RUNNING、需求2工作IDLE。未发评论POST、未建立模型任务／调用计数或Chat、未代用户修改／解决／删除评论或正文。当前服务已加载修复，页面刷新后可由用户重新点击建议入口；真实生成效果由用户实际操作，不冒充本轮已付费验收。此节替代上文修复完成时“服务待加载”状态。


最终静态收尾：14份责任Markdown的268个本地链接有效；git diff --check退出0（仅既有换行规范提醒）；cleanup-test-artifacts.py --dry-run退出0，JSON=0／截图=0。正式设计／归档及映射已同步。没有浏览器媒体或JSON报告，本轮未提交推送Git，旧48fab5b为上次同步。
