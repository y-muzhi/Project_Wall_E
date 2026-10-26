# 事实确认、评论与历史恢复浏览器检查

2026-10-23，基于a8dc673工作区。Playwright CLI 0.1.22／独立Chrome、临时生产前端、真实FastAPI／Worker／SQLite，私有离线Counter／Gateway；真实API为0。准备数据通过临时HTTP接受GENERATE及带精确证据的DISCUSS；浏览器真实选择事实确认并点击确认写入。

已完成单元：FACT_CONFIRMATION展示绑定Movie brief、全部补丁原文与替换内容；选择确认后V1→V2、正式答案保存、提示已写入。只读核对guide_runs=2、llm_uses=2、revisions=2、suggestion_batches=0、manual_edit_sessions=1，确认没有再调用模型／新建批次。阶段业务状态未作为额外门禁。

夹具初次错误使用区块writable筛选DISCUSS正文（正确值全部false），导致私有返回生成失败；修正夹具为实际已携带区块的精确提案，不放宽产品授权，C06仍独立校验补丁及证据。初始临时槽fzab295n已close／stop并清理，离线count2／Chat2。当前进程PID49640、端口56028、会话61065，浏览器v15-b7，临时目录walle-v15-browser-t2f_v_mc；后续评论与历史恢复仍进行中，结束后补最终结果及清理，不能将本记录当整版验收。

## 评论、历史恢复及双标签入口最终单元

浏览器原生操作：点正文区块→评论区块→添加评论“补充推荐规则”→更多→让AI修改。实际PROPOSE_CHANGES运行#3完成并出现原目标候选，正文仍V2；接受后显示决定尚未应用，完成本批并确认应用才变V3。历史列表查看V1、恢复到编辑草稿并确认，界面显示基于正式正文v3的人工草稿；完成后形成V4，四份CONTENT的version_no／source_content_version均1—4，恢复原文仍可读。总guide_runs／llm_uses为3／3、comment1、batch1，历史恢复不再调用模型。

同一Chrome上下文新开第二标签，同时原生点击两页人工编辑按钮：一个成功创建草稿，另一个显示“当前已有其他操作占用正文”。只读库核实CURRENT V4、唯一MANUAL_DRAFT id4，manual_edit_sessions两COMPLETED、一EDITING；未创建重复草稿或内容。成功页点击取消并确认放弃，另一页reload后无alert，当前只读正文仍是恢复后的V4原文。这里只证明双标签编辑入口竞争，不扩展为全部双标签自动保存／断网恢复竞争通过。

最终清理：浏览器v15-b7 close，服务61065收到stop正常退出，离线计数3批／Chat3次；目录t2f_v_mc不存在。最终人工草稿取消后CURRENT V4，后续布局使用另一完全独立临时库。
