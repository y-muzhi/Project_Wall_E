# V1.5 人工编辑、历史与评论专项

- 日期：2026-10-22；未提交的当前工作树，正式前后端设计1.0／EFFECTIVE。后端Python／SQLite、FastAPI进程内ASGI；隔离TemporaryDirectory，退出即清理，未启动监听服务。
- 实现：编辑请求显式绑定document_id／manual_draft_id／基准版本；自动保存幂等且只保存草稿；恢复同文档历史至新草稿；完成经统一正式提交事务保存正文、CONTENT、内容事件及同文档评论锚点，NO_CHANGE只结束编辑。旧确认保留，新稿未确认。SPEC保护实际已有的固定标题，轻量文档可编辑。
- 历史按文档分页；人工说明形成VERSION_MARKED事件，返回已有Revision及新事件，不新增或修改CONTENT。markers投影确定为event_id／description／created_at，按时间及事件ID升序。
- 评论创建／分页／完整索引显式目标；后续命令沿原评论固定document_id。归档只读；占用阻止维护；五态不影响权限。正文提交只重新定位该文档评论。
- 命令：`.venv\Scripts\python.exe -m pytest backend/tests/documents/test_v15_documents.py -q -p no:cacheprovider`：11 passed，32.00秒。
- 命令：`.venv\Scripts\python.exe -m pytest backend/tests/revisions/test_v15_history.py backend/tests/comments/test_v15_comments.py backend/tests/documents/test_v15_editing.py -q -p no:cacheprovider`：17 passed，50.56秒。覆盖真实HTTP、跨文档隔离、幂等与并发版本、取消、恢复高水位、确认保留、审计失败事务回滚、历史不可变、归档／占用保护及局部锚点。
- 初次编辑专项失败由无效评论夹具锚点导致，修正为真实BLOCK锚点；历史首次夹具缺setup导入、HTTP夹具误用runtime名称及缺executor，已修正。保持生产边界检查，不放宽来源／运行时约束。
- 唯一警告：现有Starlette TestClient使用httpx的弃用提示；未为本单元升级依赖。
- 未覆盖：前端新契约／交互、候选及AI调用方、全量旧业务测试、浏览器、供应方与真实计数／模型。当前新资源仍OFFLINE_READY；这些专项不能作为完整V1.5产品验收。
- schema150的manual_draft_context新增source_refs_json，仅对新库生效；未初始化或修改用户业务库。没有原始测试JSON、截图、录像或日志留存。
