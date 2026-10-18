# 初始化回答后推进修复专项记录

日期：2026-10-11。关联：FLOW-002；历史排查FLOW-001。

## 1. 授权与范围

用户要求解决重复提问并记录独立迭代文档，随后明确“允许离线专项并重启后端”。本轮仅必要的离线用例、只读回放和服务加载；不调用真实Tokenization／Chat，不代提交答案或改正文，不恢复完整验收。用户选择继续回传问题／所选名称／填写内容，不扩大为全部卡片说明。

## 2. 首次执行、失败与修复

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest backend.tests.guide.test_initialization_progression backend.tests.infrastructure.test_context_layout backend.tests.infrastructure.test_full_template backend.tests.infrastructure.test_versioned_resources backend.tests.guide.test_result_persistence.ResultPersistenceTests.test_real_confirmed_fact_adoption_uses_initializer_source_keeps_creation_and_increments_once backend.tests.guide.test_orchestrator.OrchestratorTests.test_retry_rate_limit_then_unknown_output_field_then_success_same_call_exact_three_requests backend.tests.guide.test_orchestrator.OrchestratorTests.test_real_tcp_audit_commit_before_send_and_actual_c07_completion_no_open_sql -v
```

31项、61.611秒，退出1。26项通过、4项ERROR、1项FAIL。新增初始化检查取用MessageRepository.guide简略投影，误以为有prompt_version／context_template等字段；历史协议恢复因IndexError中断，编排变为通用内部错误，因此新重复拦截与确认推进用例失败。该问题属于本次生产实现错误，不归因于模拟模型。

修复：`initialization_progression.py`改为GuideRepository.get完整记录，按实际原卡冻结Function／Prompt／Context恢复；不放宽校验或制造字段默认值。

修复后仅重跑受影响5项：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest backend.tests.guide.test_initialization_progression.ProgressionGateTests backend.tests.guide.test_initialization_progression.ProgressionOrchestratorTests -v
```

5项、19.225秒，退出0，全部通过。合计31个不同用例在首次或修复后通过，不表述为一次完整31项通过。

## 3. 覆盖与证据性质

- 新初始化v6／v7独立冻结；其他任务保持v4／v5，历史v1—v5恢复且不新增推进规则；资源改动拒绝，无旧版本回退。
- 新旧预算一致、输入输出Schema一致、稳定传输及真实计数／审计入口一致；新版Prompt字节数少于原版。计数回执为合成数据，不证明真实token长度。
- 原题已回答：换card_key、插入空白、全半角问号及英文大小写等展示差异不能绕过检查；相同key的新细问题允许。
- 已跳过及不在实际发送Read Manifest中的答案不阻止提问；旧v5检查行为不被追溯改变。
- 隔离数据库真实命令推进：普通选择→具体完整CONFIRM→用户confirm→原事实证明校验→正文版本增加；普通选择阶段不自动写正文。
- 无进展结果：一次合成模型响应即验证失败，固定安全原因保留审计；无自动重试、无新助手卡片、无正文变更。
- 原事实采用回归及普通失败三次重试／实际本机TCP审计提交分支保持。TCP服务器只在本机返回受控夹具，未访问供应方。

测试使用隔离临时SQLite及合成／本机响应，未使用正常业务库创建测试需求。临时夹具清理，不留测试JSON、截图、录像或原始日志；正式资源和既有业务审计保留。

## 4. 离线准入与真实历史只读回放

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/ai-service.py
```

退出0，普通／完整模板六任务准入启用，完整模板预算65536／131072／8192 token、余量1024。构造阶段不读密钥、不访问业务库或模型。

真实历史回放使用SQLite `mode=ro`，从Run8／9原请求审计恢复原wire与冻结协议，读取实际C03快照，单独对原输出应用新初始化问题检查；两轮均返回InitializationNoProgress。没有修改原审计、结果、消息或状态。首次辅助脚本未显式BEGIN而被DocumentSources共享事务检查拒绝；补上只读事务BEGIN后回放成功，回滚并关闭连接。该辅助脚本错误未导致业务数据变化，也未修改生产事务要求。

该回放仅说明原重复结果能被新规则识别；不把新Function应用到历史运行并声称其旧验证不合法。

`git diff --check`通过，未运行额外类型检查、构建或全项目测试。

## 5. 后端加载与只读观察

重启前正常业务计数为需求／运行／LLMUse／消息=3／10／12／25；无RUNNING／WAITING_USER，REQ000003 CURRENT13／v1。向原终端发送Ctrl+C，进程31608及8000监听消失。停止返回退出1，未取得完整关闭生命周期日志，不称为优雅关闭验证。

```powershell
.\.venv\Scripts\python.exe -u -X utf8 tools/ai-service.py --start
```

新进程35852于本机18:53:24启动；应用启动完成，8000监听正常。`-u`仅使启动文本立即输出；模型、数据库及服务参数保持。

GET后端需求列表、5173前端代理REQ000003详情及消息均成功。重启后计数仍3／10／12／25，无进行中AI任务，CURRENT13仍v1；新目录初始化默认版本v6／v7。没有发送业务POST、替用户继续运行或调用模型。旧卡片／答案保持，新接受初始化才采用新规则。

## 6. 未覆盖

真实模型是否遵循推进提示、真实System计数与成本、具体确认卡质量及所有语义改写重复未验证。确定性检查以原问题文本为界，不声称理解全部同义问题；模糊或矛盾答案需要模型生成针对性细问。输入仍按原预算精确计数，超限拒绝Chat；未开启深度思考。

本轮没有浏览器交互／截图、前端构建、全项目验收。现有用户业务库未代执行新的答案提交或事实写入。
