# V1.5恢复、来源与离线浏览器联调

2026-10-23；当前未提交工作树。保留既有文档整理及其他改动，不执行Git写操作。正式设计1.0／EFFECTIVE，默认资源v10／OFFLINE_READY；本记录不构成真实供应方准入或版本整体验收。

## 恢复与前端专项

- C09、Worker及execution：`.venv/Scripts/python.exe -m pytest -q backend/tests/guide/test_v15_recovery.py backend/tests/guide/test_v15_worker_recovery.py backend/tests/guide/test_v15_execution.py`，19 passed，92.75秒。涵盖已持久化但未解析的响应、唯一真实返回的同事务C07恢复、未知发送不重试、证据失败保留原始返回、启动恢复、关闭释放OS锁、执行租约退休与提交竞争。恢复不读取环境凭证、不计数或Chat。
- 后续cards／batches／local_revision相关21 passed，122.39秒。此前全V1.5联合130 passed／529.45秒是C09改动前的基线，不能标为最新全量。
- 来源读取、阅读选择、卡片整组暂存、路由／自动保存等：Node执行`tests/v15-*.test.mjs`、`detail-layout`、`application-router`、`autosave`、`manual-start`、`model-calls`、`suggestion-batch`、`workbench-history`，99 passed，547.96毫秒。新增人工Wire专项1 passed，204.55毫秒，分别核对保存／取消／完成的真实HTTP字段及原key重放。尚未把旧V1.0全部专项转换或宣称全量通过。
- 完整`tsc --noEmit`及临时生产构建通过，1251模块，548毫秒；只有既有大chunk提醒。未覆盖用户`frontend/dist`。本地恢复缓存仍使用manual_draft_id，HTTP正式输入使用draft_id，不混为一处改名。

## 浏览器实际路径

使用Playwright CLI 0.1.22离线缓存及本机Chrome，隔离浏览器；`tools/serve-v15-offline.py --serve`创建TemporaryDirectory内schema150 SQLite、真实FastAPI／GuideWorker及临时生产前端。Counter／Gateway仅该测试进程私有注入；没有读取真实凭证、没有外部模型／计数请求或放开资源文件准入。实际离线计数4批、Chat替身4次。

1. 工作台三字段创建“电影助手离线验收”；真实库一条初始USER、零文档、零GuideRun、零LLMUse。
2. 实际发送讨论→出现出稿建议→展开真实消息来源→整组接受，生成并直接保存“电影需求说明”V1；零文档状态自然转到第一份实际文档。确认当前Revision后显示已确认。
3. 请求详情读取已保存8分区、8项计数、1024预留及131072／8192／139264上限、Prompt v2和实际请求，查看不新增调用。
4. 请求修改建议，先EDITED保存决定，正文保持V1；完成后写入V2。首个旧前端因把8字段正文回执按完整DocumentView解码，误报UNKNOWN；修复后以捕获的原body与原key重放，返回同一Revision2及DocumentEffect，没有重复CONTENT。此原动作重放使用显式本机测试HTTP，不冒称热更新后的旧UI闭包恢复成功。
5. 新批次正常UI接受→完成→确认，显示“本批修改已应用”，V3未确认，旧V1确认保留。
6. 人工编辑初次PUT发现前端错误传manual_draft_id，服务器422且未保存。按正式draft_id修复；刷新时beforeunload提示，本地未同步草稿可恢复。选择“恢复本地内容”后自动保存成功，完成编辑生成V4未确认。没有丢弃这次失败记录。
7. 新建空白“只读参考B”V1，不Chat；再次编辑A并阅读B，页头明确当前B／正在编辑A。回到A保持原草稿；修改后缩至1000px，自动保存并显示窄窗保护，恢复1024px保留文本。取消编辑→确认放弃，A保持V4、B保持V1。
8. 实测1024／1100／1280／1440／1920px，documentElement.scrollWidth等于视口宽度；1100px导航抽屉，1024px可打开并关闭抽屉；1280／1440／1920导航200px，辅助面板实际396／420／420px。只记录本次DOM几何与原生交互，没有宣称逐项视觉、全部焦点及长表格验收。

修复还包括：零文档消息预览复用启动时只读parser；第一份生成稿后不再停在空阅读；已答行动卡片展示实际正式execution_selection；候选完成复用8字段正文校验，不放宽普通DocumentView解码。最终修复后页面控制台0错误／0警告。

## 清理及边界

关闭仅本次`walle-v15-20261022`浏览器，向本轮exec会话发送stop，测试进程20760正常排空并输出清理完成。临时目录walle-v15-browser-c4erijl8已不存在，54086端口释放；8000／5173无监听，没有操作用户服务。临时SQLite、构建、CLI快照及日志随TemporaryDirectory删除，不留JSON／图片／录像／原始日志。

退出前只读核对：两个CURRENT，A V4／B V1，根IDLE，4个GuideRun及4个LLMUse，5个CONTENT Revision，人工草稿已取消并移除。真实模型效果、资源LIVE_VERIFIED、所有A15／EV和另一业务类型仍需分别收口；当前不以本次电影离线流程替代真实语义效果。
