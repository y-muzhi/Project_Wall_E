# V2.0前端严格错误与原请求回执读取

日期：2026-11-05；HEAD 28a7c9e，V2未提交。依据BE6.1、APP-COMMAND-CLOSE／QUERY完整契约及FE6.1／7.4。仅前端API与解码，本单元未新增页面或改变业务正文。

实现：
- code-command-registry.ts登记同后端48个业务POST身份，CODING／TESTING、能力decoder_kind、规范路径及安全整数参数固定；GET／关闭控制自身不登记为业务意图。小写UUID4、原路径／参数／module重验，公开目录及每项不可变。
- code-errors.ts分离V2错误HTTP／固定文案、两字段输入错误、授权／就绪／冲突／COMMAND_CLOSED结构。每入口独立白名单，未知字段／状态／HTTP／文案不按确定拒绝处理；原文档错误协议保持原样。
- 现有ApiClient增加本地原生错误policy，仍同一个请求截止／取消／同源／success-data-error-meta通道；准备及读取时冻结policy方法，V2写5xx保持UNKNOWN。没有独立fetch、动态加载记录代码或放宽旧文档decoder。
- code-command-receipts.ts严格核对lookup／record／原HTTP／outcome组合、原模块／task身份及结果中的关联ID；FOUND202要求真实operation关联；CLOSED必须原409 COMMAND_CLOSED并匹配原路径／方法。成功和拒绝由原入口本地policy／decoder核对，不从当前表单或当前任务重建结果。
- WalleApi.commandReceipt接实际原模块GET回执入口，只带原method／path／key查询参数，无body、无Idempotency-Key header，也不生成UUID。读取NOT_FOUND仅结果事实，本单元不删除记录或派发旧业务。

检查：
1. 新回执8项＋原ApiClient13项＋预算3项：24通过，strict typecheck／format:check通过。
2. tools.quality_gate.commands＋environment的离线前端全套465通过、无跳过（7094.57毫秒）；类型／格式通过，临时生产构建通过（1.03秒）。有既有大chunk提示，未关闭提示或改阈值。所有构建输出在本轮Temp/frontend-build并已清理，未写frontend/dist或更新用户静态服务。
3. 随后补结果data.operation_id与回执association一致性检查，新增错误关联用例仍包含在24专项内；24再次通过、strict及format通过。此微调晚于上述全套／临时构建，不把它描述为微调后再跑的465。git diff --check另随本轮收尾核对。
4. 修改前netstat对5173／5174／8000未输出监听，未启动／重启开发服务；没有需恢复的实际开发模块。只表示该次端口观察，不证明所有服务／任务不存在。

命令：node --test tests/v20-command-receipts.test.mjs tests/api-client.test.mjs tests/v20-code-values.test.mjs；npm run typecheck；npm run format:check。扩展检查使用tools.quality_node.cjs预加载、--test-isolation=none及专属临时目录，保护正常数据／凭据与外网；无测试JSON、截图、日志留存。

未完成：48原业务完整输入／成功DTO登记随真实B1／B2入口完成；当前OriginalResultPolicy是本地程序依赖，不能从IDB反序列化为代码。FrozenCommand受控导出／恢复、prepareCloseOriginalCommand、REQUESTED CAS、IDB v4／墓碑及设置／任务页面未实现，不以只读回执接通称完整恢复流程。没有浏览器／跨页／掉电／真实端到端或供应方验收。
