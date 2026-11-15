# V2.0 代码任务启动前配置应用专项（2026-11-10）

基线 master 28a7c9e，Schema200 db20-r43。本轮按 BE 0.17-draft-17 APP-CODE-CONDITIONS／BND-CODE-API-39、FE 0.16-draft-16 BND-CODE-CONDITIONS 实现；正式设计保持原修订。

- 实际 C39 先核对任务版本、固定 Git 工具、执行配置、授权范围及未派发状态。同一事务固定原操作、配置申请和唯一授权，接收后显示待应用。保持原授权历史及同键回执。同键变更请求冲突。未执行的应用和已接收但未派发的 START 可沿原任务停止收口。
- START 原会话继续使用同一个申请及新授权。收到同一实例原生配置的可信读回后，才同事务保存生效；缺原生证据保留待核对，不能靠重发或单凭原生会话编号升级。原始配置生效证据为固定会话测试夹具，未运行真实 OpenCode 模型或计数。
- 隔离 Windows NTFS／SQLite／ASGI：`tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider`，对 C39、START、START 原会话、STOP、运行中 STOP 与预算 6 个专项文件执行，26 项通过。
- 前端 `npm run typecheck`、`npm run format:check` 与现有 Node 全套通过。自有 Chrome `tools/verify-v20-command-recovery.py --probe tasks`：C39 独立表单在 360／1280 像素下可用，取消保留草稿；首次 POST 模拟接收响应丢失，刷新从原命令恢复，仅 1 次写请求。等待与有效状态以原 API 夹具驱动；现有任务页及代码开发导航回归通过。原 Job 和临时输出已清理。
- 实际 `create_app().openapi()['paths']` 与后端设计标题逐方法和路径对照，参数名归一，Coding 71／71、Testing 45／45。此为路由注册，不代表业务或产品验收完成。

活动会话的静态启动配置没有热改或自动重启。兼容动态变更需要单独的原写入隔离、受信读回和原结果恢复，现行 API 拒绝、页面说明原因。本轮未修改体验库、未更新服务、未提交。

复查加强了生效记录的来源验证：原 START 会话、实例、代次、会话步骤结果及原运行清单摘要需相互一致。修正将配置生效错误依赖首条消息也成功的校验后，C39 四项复验通过。配置是否真实应用与首次消息送达分开。

隔离真实前后端补验：`backend/tests/infrastructure/test_v20_live_configuration_browser.py` 1 项通过。安装的 Chrome 加载实际 Vite 生产构建，由实际 Uvicorn／FastAPI 提供页面及 API，数据库使用新发布的 Schema200 db20-r44。首个 C39 请求实际返回 202 后浏览器端丢弃响应；刷新通过原键找回同一操作，SQLite 只有一次配置申请，未创建实例，页面保持待应用。该专项仅验证启动前，不触发 OpenCode／模型。测试进程、浏览器 Job、静态构建及隔离库已回收；PID 8712 的原体验服务未更新。

发布 `db20-r44` 仅更新 Schema 构造来源中的 Coding 命令注册表固定摘要。三份结构资源与 r43 字节一致；新清单 SHA256 为 `97dd61115514f4fa688ce3c6c44601e5d204b3ca34d1d414a761be355644749a`。没有迁移体验库。

22:44 最终页面回归后的真实 Chrome／Vite／FastAPI／隔离 r44 复验 1 项通过；仍仅一次 C39，丢失原响应后无新配置请求。原体验服务复查 PID 8712、首页 200，继续使用先前构建。
