# V1.5 讨论程序命令专项

2026-10-22，未提交工作树；Python隔离SQLite／OS进程锁／FastAPI进程内TestClient，Node离线前端；没有真实模型或计数、用户库写入、用户服务启停或Git写操作。

后端`python -m pytest backend/tests/requirements/test_v15_discussion.py -q`：最终10 passed，33.28秒。四种互斥命令／同归属来源与真实答案／运行分析／版本竞争／原键重放／占用／无变化／用户阶段历史／审计失败整事务回滚已覆盖。此前基础＋讨论＋文档＋人工编辑＋历史＋评论联合46 passed，120.10秒；新增最后两项SourceRef后仅重跑受影响讨论专项。原Starlette/httpx弃用警告仍在。

前端`node --test tests/v15-discussion.test.mjs tests/detail-layout.test.mjs tests/v15-local-state.test.mjs tests/v15-directory.test.mjs tests/v15-reading.test.mjs tests/autosave.test.mjs tests/v15-foundation.test.mjs`：41 passed，401.61毫秒。覆盖懒加载、取消读取、并发旧响应丢弃、原键核实、确定提交后的只读恢复、讨论版本／占用和既有PATCH严格响应；完整tsc通过。临时Vite构建1248模块／447毫秒通过，仅既有大chunk警告；输出目录已清理。

首次后端失败定位到公共canonical_input只允许对象，不能直接序列化消息metadata数组或校验primitive Ref／PhaseKind；改用严格基础字段校验及合法数组序列化。其次修正HTTP DocumentKind到Discussion小写profile的真实映射，没有放宽冻结Schema。前端响应比较改为忽略对象键顺序，数组次序保持。一次构建日志采集遇到GBK解码失败，临时目录清理后明确UTF-8重跑确认构建成功，未把未知结果算通过。

前端已挂讨论摘要／大纲面板、目标来源绑定、主题切换、用户阶段确认和处置；尚未浏览器验证。来源显示已有真实引用，定位交互和完整AI增量仍待后续单元。RUN_MATERIAL可验证保存的ContextBasis.selected，真实新布局快照正例待B5；未执行供应方兼容或模型效果。程序命令不会创建GuideRun／LLMUse／文档，不改变业务状态。

## 历史恢复入口接续

复用ManualDraftStart，显式绑定当前目标／基准与不可变restore_revision_id；恢复只建立新草稿，完成编辑后才形成新CONTENT。UI在只读历史提供恢复确认／UNKNOWN原请求核实／已接受后的只读恢复。回执检查实际target_document_id、base_content_version、恢复正文及ID高水位；历史和当前文档不能串用。

`node --test tests/manual-start.test.mjs tests/v15-discussion.test.mjs tests/v15-directory.test.mjs`：16 passed，235.37毫秒；新增恢复范围／高水位专项，原开始编辑专项同步显式document_id和五态。此处仅离线命令证据，未浏览器交互验收。
