# 完整模板／上下文专项及服务更新记录

日期：2026-10-11。关联：TPL-001、CTX-001、TPL-002。

## 授权与范围

用户明确“允许检查并重启后端，解决当前报错”。本次仅执行模板、上下文、历史资源的离线专项及服务只读检查，在确认没有进行中AI任务后重启后端。使用隔离测试数据库及模拟计数，不调用真实Tokenization／Chat，不替用户提交创建，不修改正文或保存版本，不恢复完整验收。

## 命令、结果与修复

首次命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest backend.tests.infrastructure.test_full_template backend.tests.infrastructure.test_context_layout backend.tests.infrastructure.test_versioned_resources -v
```

20项、30.927秒，退出1：18项通过，2项上下文计数回放报错。原因是FixtureCounter模拟回执的data行缺少object、token_ids、offset_mapping必填字段；正式回放校验拒绝该回执。修复仅补齐模拟回执，不放宽生产校验。首次失败保留，不称为首次通过。

另新增隔离回归：旧目录对new-requirement@v2返回TEMPLATE_INVALID；切换到新目录后相同创建载荷及幂等键返回CREATED，数据库仅一条需求，Provider调用数为0。

修复后命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest backend.tests.infrastructure.test_context_layout backend.tests.infrastructure.test_full_template.FullTemplateCreationTests.test_rejected_old_catalog_request_succeeds_with_same_key_after_catalog_update -v
```

7项、17.680秒，退出0。上下文6项和新回归1项全部通过；合计21个不同用例在首次或修复后通过，不表示一次完整21项重跑。覆盖模板原字节／标题及预算绑定、资源篡改拒绝、历史冻结版本恢复、两预算六任务、布局往返及稳定前缀、身份配对拒绝、计数／发送／审计同文、裁剪回放、隔离创建与幂等重试。

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/ai-service.py
```

退出0。普通及完整模板六任务准入启用；完整模板分项65536、输入131072、输出8192 token，封装余量1024。该工具离线模式不读密钥、不打开业务数据库、不请求Provider。计数专项使用合成回执，不能证明供应方真实token数量。

## 实际服务处理

重启前GET需求列表及两条详情成功；实际业务库以SQLite URI mode=ro只读检查。需求／AI运行数为2／6；运行状态4条COMPLETED、2条FAILED，无RUNNING／WAITING_USER。需求2为MANUAL_EDITING／MANUAL_DRAFT，需求1为IDLE，未把需求1的INITIALIZING业务状态误判为正在请求模型。

向原终端会话发送Ctrl+C后旧进程52312退出，端口8000释放。停止命令返回退出1，未得到完整关闭生命周期日志，因此不把它作为优雅关闭已验证的证据。确认旧进程和监听都已消失后，执行原启动命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/ai-service.py --start
```

新Python进程31608于本机17:58:34启动；应用启动完成，监听127.0.0.1:8000。前端5173开发服务继续运行，无需生产构建。GET `http://127.0.0.1:8000/api/v1/requirements` 与 `http://127.0.0.1:5173/api/v1/requirements` 均成功、列表仍为需求2和1；重启后只读检查仍为2条需求／6条运行，无进行中AI任务。本次没有向业务服务发送POST。

源码与新资源加载后，旧进程不认识模板导致的422原因已处理。实际用户提交未代为执行，因为创建成功将按现有流程自动调度AI初始化。

## 未覆盖与留存

未运行前端构建、类型检查、浏览器交互或全项目回归；未检查真实模型计数／Chat兼容、实际System预算、长上下文效果、缓存命中率、费用以及正常业务库的创建端到端结果。保留原有预算门禁和业务保护，不把上述离线通过写成模型兼容证明。

仅记录Markdown；专项临时数据库由夹具清理，没有留存测试JSON、截图、录像或原始日志。正式资源JSON、业务数据库和既有审计保留。
