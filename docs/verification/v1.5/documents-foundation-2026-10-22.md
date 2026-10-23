# V1.5 多文档基础及批次回归

- 日期：2026-10-22（Asia/Hong_Kong）；未提交工作区。范围为B1资源、B2需求后端基础、B3创建／读取／文档属性及确认单元。
- 实现：多CURRENT独立身份；空白或服务端固定框架；V1 CONTENT及创建来源事件同事务；正文读取必传同需求document_id；改名／归档／恢复／当前Revision确认使用metadata_version与幂等；确认不改正文／需求状态，不新建Revision。
- 新建来源使用本次用户创建动作的不可变USER TEXT消息，origin为真实MESSAGE引用；不把初始描述伪装成本次创建动作，不复制成AI消息。DocumentChange的判别字段为type；创建结果为{document,revision_id}，属性结果为{document,event_id}，NO_CHANGE的event_id为null。这些是正式设计所述具名结构的具体序列化选择。
- 环境：项目`.venv`；全部SQLite在TemporaryDirectory中；真实FastAPI路由与生产factory／lifespan以进程内ASGI验证，没有监听服务、供应方请求或用户数据库访问。

## 命令与实际结果

1. 文档／需求专项：`.\.venv\Scripts\python.exe -m pytest backend/tests/documents/test_v15_documents.py backend/tests/requirements/test_v15_foundation.py -q -p no:cacheprovider`，20 passed，39.53秒。
2. 最终受影响回归：`.\.venv\Scripts\python.exe -m pytest backend/tests/test_v15_service_foundation.py backend/tests/documents/test_v15_documents.py backend/tests/requirements/test_v15_foundation.py backend/tests/infrastructure/test_collaboration_resources.py backend/tests/infrastructure/test_schema_transport.py backend/tests/infrastructure/test_versioned_resources.py backend/tests/documents/test_snapshot.py backend/tests/shared/test_validation.py backend/tests/shared/test_http_errors.py -q -p no:cacheprovider`，**74 passed、90 subtests passed**，63.27秒。
3. 前端类型检查：以现有node运行`frontend/node_modules/typescript/bin/tsc --noEmit`，cwd=frontend，通过。
4. 生产构建：以现有node运行`frontend/node_modules/vite/bin/vite.js build --outDir <TemporaryDirectory>`，cwd=frontend，通过，1240模块；构建目录自动清理，未覆盖frontend/dist。前端业务代码本轮未适配，这只是现有客户端的编译基线，不是V1.5契约接入或页面验收。
5. `git diff --check -- backend/app backend/tests`最终通过（只读Git检查）；清理工具`--dry-run`显示JSON=0、screenshots=0。8000／5173最终仍无监听。

覆盖：同名多文档不合并、三类固定框架与原模板字节、空快照、精确目标读取／无回退、跨文档确认拒绝、重复确认／归档NO_CHANGE、元数据不增加正文版本、关闭状态下正常维护、占用／并发／幂等保护、消息／文档／Revision／事件失败回滚、严格HTTP、生产工厂创建无调度及退出释放锁；原快照算法／通用校验／安全错误投影及历史资源静态回归。

## 失败与修正

- 扩大回归首次70 passed／4 failed：原VersionedAcceptanceTests仍要求V1.0创建即初始化、旧WAITING_USER和旧卡片承接，与D15-005及V1.5创建规则冲突。将这4项改为实际新库上的零运行创建、旧字段拒绝、上下文GET无隐式初始化及旧初始化入口拒绝；历史v1／v2资源摘要与精确restore测试继续保留。没有添加legacy执行分支或忽略失败。其他旧版业务专项尚待按所属单元更新，未跑全库测试。
- 旧夹具在setUp失败后未释放临时锁的清理提示：替换夹具，在取得锁前登记TemporaryDirectory清理、锁取得后登记释放；本轮3个已释放残留锁目录已按确切路径清除。早期pytest tmp_path保留的本轮pytest-14／15／16已核对目录内容后清理；新专项统一使用立即清理的TemporaryDirectory，不再依赖pytest保留策略。
- 首次生产构建经cmd／npm转发时输出路径引号被作为字面量保留，Vite无法创建目录；改为Python subprocess参数数组直接调用现有node／tsc／vite后通过。这是构建命令问题，未改产品或锁文件。
- 存在现有Starlette TestClient的httpx弃用提示，以及既有前端大包提示；未扩大为依赖升级或打包重构。

## 明确未覆盖

人工编辑／恢复／统一内容提交、V2→V3历史确认保持、Revision列表／人工标记、评论／批次全调用点、讨论命令、AI接受／卡片／上下文／计数／保存／取消恢复及新前端接入均待继续。本轮无浏览器、真实Tokenization／Chat或模型效果验证，无用户服务启停、现有业务数据修改或Git提交／推送。资源仍OFFLINE_READY。
