# 授权批准、查询及设置命令浏览器恢复（2026-11-05）

## 依据与实际接入

master／HEAD 28a7c9e，V2尚未提交。BE0.17-draft-17／FE0.16-draft-16（DRAFT）摘要沿[执行配置记录](execution-profile-versions-2026-11-05.md)，本轮未改两份设计或合并pending。补读OBJ-CODE-POLICY授权与应用结构、APP-CODE-SETUP批准、APP-CODE-QUERY4.1—.5、API15／16／23完整输入／响应及APP-CODE-CONDITIONS4.1—.5；没有实施其配置应用流程。

新增POST /api/v1/code-authorizations、GET同一路径及GET /api/v1/code-authorizations/{id}，原14条V2实际业务HTTP增至17条。复用原共享事务、全局sequences、原键账本、关闭、回执及V2边界，不新建授权服务或并行存储。另7个页面壳不计为业务API。

authorization_scope.py固定七项范围字段及完整ExecutionLimits。write_workspace_only必须字面true；目录／命令／网络／模型引用数组不重复；全部限制正安全整数、交付窗口≤300秒，不能扩大原配置任何上限；模型及命令为配置子集。本地交付获批前必须存在原配置delivery；只读根／网络目标精确匹配SCOPE目录及类型。空集合不补权限，不接受自由路径、供应商秘密、默认模型或自由Shell。

authorizations.py同一事务核对真实不可变执行配置及检查／依据，允许为未就绪配置保存批准记录，但只写APPROVED_UNBOUND、task_id=null。批准者直接复用windows_private_package.current_operator_sid读取当前后端本机operator token身份；原函数拒绝模拟线程及AppContainer身份，仅查询、不改变权限／ACL／token。客户端不能提交actor_ref、approved_at、task_id或status。原键成功回放不重新读取资源或批准者；未知提交只查原结果，不产生第二条授权。

读取同快照校验结构／状态／原配置子集；坏JSON、重复键、异常状态与越权存储拒绝，不修复或回显私有正文。列表每页20，采用记录创建时刻approved_at DESC,id DESC（对象无created_at）；保留真实越界空页。status／task_id精确匹配，任务筛选不存在返回NOT_FOUND。批准未绑定与BOUND_PENDING_APPLY／EFFECTIVE／APPLY_FAILED／APPLY_UNKNOWN／RETIRED分开；不根据显示状态声称运行时有效。

authorization_api.py接三条实际入口；configuration_api.py／service.py参与路径及退役lease错误契约；command_registry.py增加C15成功结果AUTHORIZATION；EntityKind.AUTHORIZATION_GRANT复用原sequences。另发source-bound db20-r10，manifest SHA256 db6f8e3cade6dc30d37c9902d90b7afeb7bc2b37ce60fc2e72e2758c7d7156e9；r1—r9未覆盖，实际load_release已通过。只发布仓库Schema资源，不是维护正常数据库或部署服务。

前端code-authorizations.ts／WalleApi接Typed批准／详情／筛选列表、严格scope／状态关联、C15原输入及201结果decoder；configurationRecovery增加原C15 binding。ExecutionLimits从code-execution-profiles.ts导出复用，无新any／忽略检查或第二套限制规则。这里只是API及原命令存储，完整设置页面仍待实现。

## 检查与修复

环境仍为Python3.13.5／固定SQLite3.54.1／Ruff0.17.3及Node24.15.0／既有锁定依赖。后端经tools.quality_gate.environment专属临时根、tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short与专属--basetemp，在普通非提升测试环境执行。

- 首轮授权＋发布维护：23通过／1失败69.36秒。批准入口只有body_fields声明却未实际调用object_fields，多余字段被忽略，尚未取得配置时返回404。已在实际parse入口先检查精确字段，再读取配置；不是改测试期望或在业务层吞字段。
- 修复并增加21条历史分页后，最终test_authorizations.py／test_execution_profile_versions.py／test_v20_published_schema.py三文件47通过175.39秒。涵盖真实ASGI／事务／原生批准者SID、scope不可变及收紧、登记资源类型、原键拒绝／成功／关闭、身份不可用时无ID消费、提交ACK丢失、scope坏存储、容量、筛选及真实空页，同时回归执行配置和当前发布维护。
- 当前operator SID由真实Windows API返回并与实际写入actor_ref比较；只操作本轮隔离授权记录，未应用授权或改变系统权限。执行配置／价格／资源仍为明确测试夹具，不能充当生产准入。
- 前端授权与执行配置专项17通过0.61秒；npm test全套515通过6.72秒；npm run typecheck与npm run format:check通过。
- 197个backend/app文件Ruff格式通过；authorization_scope／authorizations／authorization_api及configuration_api／command_registry lint通过。早期循环变量遮蔽、查询校验导入及前端浏览器status拼写问题均在最终检查前修复，未关闭规则。identifiers原基线lint仍见前批，未冒称全仓库lint通过。
- 最终隔离临时生产构建通过1.18秒，未覆盖frontend/dist；git diff --check和db20-r10实际load_release通过。既有httpx弃用提示未升级依赖。

## 实际浏览器证据

使用已安装Playwright CLI和本机Chrome、项目playwright技能。先核对npx存在，不安装依赖或联网。扩展原tools/verify-v20-command-recovery.py／.mjs的--probe configuration选择，仅执行受影响设置原命令，不机械重跑既有容量／blocked专项；默认all保留原完整检查行为。

命令：

.venv/Scripts/python.exe -B -X utf8 tools/verify-v20-command-recovery.py --cli-entry C:/Users/羊牧之/AppData/Local/npm-cache/_npx/ef40dfadc1438043/node_modules/@playwright/cli/playwright-cli.js --probe configuration

frontend/tests/browser/v20-command-recovery-probe.ts新增configurationProbe，实际使用WalleApi.configurationRecovery及当前三类C07／C08／C15 binding；实际IndexedDB事务、原owner、关闭原连接与新连接恢复、摘要／正文和终态回执。每类检查：

1. 原输入固定、唯一key、真实IDB提交为DISPATCHING后才允许发送。
2. 测试响应丢失后保留UNKNOWN及原正文、原dispatch_count。
3. 关闭原owner／连接，新owner从真实IndexedDB恢复，禁止分配新key。
4. 显式恢复使用原正文和原键；201结果由各实际业务decoder确认。
5. 终态201回执保留，pending及正文清除。

三个业务种类全部通过，V20_IDB_BROWSER_PASSED；自有worker正常退出0，OWNED_BROWSER_CLOSED及OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED均确认。临时静态页面随机端口，仅为检查装载源码；HTTP为明确脚本响应，没有业务服务／模型效果。因此这是实际Chrome＋IndexedDB原命令组合证据，不能写成完整设置UI或浏览器到真实ASGI端到端通过。未新增截图／录像／原始报告留存，专属临时树及Job进程清理。

## 未完成与边界

APPROVED_UNBOUND不是任务绑定、生效配置或原生权限。任务创建／授权首次原子绑定、同组配置应用及真实VERIFIED证据、权限ALLOW_ONCE程序范围和UNKNOWN禁止授权仍待实际业务接入。当前真实目录缺执行器／价格等，模型证据验证器仍缺、ready=false；不会因新批准接口绕过准入。

完整设置UI、Coding／Testing任务／全部页面、仓库准入及基线／内容／秘密策略、Guard／受保护包／LPAC-WFP、模型账务及供应方证据、真实检查与交付仍在现行映射推进。未使用正常data／.env.local，未真实模型／计数、启停用户服务、系统安装／权限或网络策略改变、V2提交／推送。源码及格式结果均原子保存。工具收尾已确认本轮w2-catalogue／build及v20-idb临时根为空。
