# 普通讨论失败的启动配置恢复（2026-11-15）

## 范围与现场

承接用户要求启动前后端供使用，以及17:30讨论失败截图，排查并恢复本轮用户后台的既有模型配置。未改业务源码、正式设计、Schema、用户正文／失败记录；不涉及SYSTEM Guard、Coding模型准入或付费测试。保留其他工作区改动。以下时间为香港时间，核对至17:37。

只读既有data/wall-e-v2.0.sqlite：guide_run 3／requirement 2在17:30:53以CONFIG_INVALID结束，llm_uses总计0；此前run 1／2也同码失败。原后台stderr只有启动信息，没有保存内部异常文本。因此依据明确启动参数、当时未载入凭据的环境及orchestrator实际执行顺序定位配置缺口，不声称取得了未留存的原始异常堆栈。

## 实际原因和证据

- ResourceCatalog完整加载，当前collaboration release为fe4f421f5486120905f2735b70acefa5df2e4f69f8897856b6f2a4b3f77628ba；不是协议或模板文件丢失。
- 原后台通过-m backend.app启动，没有导入.env.local；ModelProfile.from_environment在PREPARING中先于count／Chat，缺少WALLE_MODEL_API_KEY会抛ConfigInvalid。该类错误统一映射为页面上的“所需协议或模板资源不可用”，提示未能区分凭据与准入。
- 当前V2库原来没有该release的admission文件，CollaborationAdmission.current返回OFFLINE_READY，require_live实际拒绝，原消息为Collaboration release has no verified live admission；单独加载凭据仍不足以恢复。
- 既有V1.5准入指向data/v15-observation-20261103-new-release/observation.sqlite中llm_use 1。当前资源／模型快照完全相同；用原evidence_database只读150／151／200校验、current及require_live复核，实际LIVE_VERIFIED，原计数与实际用量仍匹配。没有将不同release的旧证据转用，也没有重新调用供应方。
- .env.local只经现有read_local_credential与ModelProfile做本地格式检查；未输出或另存密钥。此检查及后台启动不证明供应方当前接受该密钥。

## 实际恢复

先核对8000监听PID11356、父启动器153644和完整项目命令；只读确认无RUNNING／WAITING_USER guide_run，code_tasks为0。仅停止本轮自己的空闲后台，5173前端PID41048保留。

随后在当前V2库对应ProcessLock下，调用现有CollaborationAdmission.approve_saved_call，对上述固定原始库／llm_use 1重新复核并原子发布引用配置；使用read_only=True的Database，未修改业务库。生成的data/wall-e-v2.0.sqlite.count-audit/collaboration-fe4f421f5486120905f2735b70acefa5df2e4f69f8897856b6f2a4b3f77628ba.admission.json是正常准入配置，不是测试报告，不能作为临时产物删除。原始证据库与旧准入保持原样。

通过Start-Process -WindowStyle Hidden启动现有.venv/Scripts/python.exe -B -u -X utf8 tools/ai-service.py --start。子进程设置绝对WALLE_DATABASE_PATH，使用原Schema200／db20-r50准入→再读取本地凭据→普通backend.app入口；密钥未进入命令行或父环境。启动器PID308636，实际监听PID311108，127.0.0.1:8000。正常日志仍在data/service-runtime-20261115-170926，新增backend-ai.stdout.log／backend-ai.stderr.log；旧日志保留。此前普通启动PID已失效，后续须重新核对归属。

## 本次检查与限制

- 同一现有release的原始供应方／计数证据只读复核通过，当前准入配置发布后require_live通过；这是本轮配置复核，供应方调用证据日期仍为2026-11-03。
- 新启动日志实际列出deepseek-v4-1-flash-260910／Schema200／db20-r50，并出现Application startup complete；ai-service只有在准入及本地凭据检查通过后才进入此处。
- 17:36只读GET后台/api/v1/requirements、5173代理同接口、5173/requirements/2均200，字节分别516／516／643。工具受限环境第一次本地socket检查遭拒，随后获准在普通用户宿主执行上述只读检查；未更改网络策略。
- 17:37只读复核run 1／2／3仍FAILED／CONFIG_INVALID，llm_uses仍0；当前count-audit目录只有正常admission文件，无新count请求记录。未重发111、未点击发送、未触发真实模型／计数。
- 配置已恢复，实际新讨论及供应方当前可用性仍待用户手动试用；旧失败消息保留，不假改成成功。原公共错误文案没有改动。
- 没有修改源码，因此未运行与本次配置无关的全量构建／测试；SYSTEM Guard暂停及完整隔离验收缺口保持不变。无提交推送、清库、数据迁移或其他服务操作。
