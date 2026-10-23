# 模型返回直接展示专项记录

日期：2026-10-11。范围：FLOW-003，延续用户已授权的初始化修复离线专项与后端重启。无真实模型调用、无代提交、无用户正文修改；原设计归档不改。

## 1. 只读诊断

Run11为REQ000003初始化v7，时间为本地19:05:45—19:06:48。LLM13／14／15传输及JSON解析成功，卡片结构也合法；三份message均不等于旧card_text序列化结果，旧业务校验因此失败，最新助手消息为空。

离线只读重放从实际保存的raw_response_json读取content，恢复原Function后检查parse_output、validate_cards与card_text。结果：三份短说明分别79／99／79字符，旧要求3728／3761／3802字符。只输出选定字段，不保存原始日志、不改审计状态或重发。

## 2. 首次问题与修复

首次后端命令选择新返回专项、重复展示、短说明卡片、完整确认写入等检查，10个实际用例通过；另有一个错误的方法名，unittest报告AttributeError，命令退出1。修正为test_choice_then_full_confirmation_then_exact_fact_adoption后通过。

新测试复用异步helper时直接注册helper.doCleanups，其helper没有独立async runner，导致部分临时锁没有及时释放，产生Windows临时目录清理警告。改为把helper的普通清理任务交给当前测试runner，后续没有此警告。首次遗留的6个临时目录只剩1字节actual.sqlite.lock；递归清理被自动审批以“blocked by policy”拒绝后，检查确切目录和文件，采用更小范围的非递归文件删除与空目录删除完成清理。没有改动业务数据库或其他临时目录。

前端首次24项中23项通过，1项旧断言仍要求缺少returned_responses的原对象，失败于兼容默认空数组。更新断言并加入不解析原文的投影检查后，24项全部通过。

## 3. 完成检查

| 命令／范围 | 结果 |
| --- | --- |
| `.venv\Scripts\python.exe -X utf8 -m unittest backend.tests.guide.test_response_display backend.tests.guide.test_initialization_progression.ProgressionGateTests.test_choice_then_full_confirmation_then_exact_fact_adoption backend.tests.guide.test_orchestrator -v` | 29项通过，退出0，35.741秒 |
| `.venv\Scripts\python.exe -X utf8 -m unittest backend.tests.guide.test_initialization_progression.ProgressionGateTests -v` | 4项通过，退出0，16.037秒；其中确认写入项与上行有重叠，不累加成不同用例数 |
| 单项`ProgressionOrchestratorTests.test_repeated_question_is_displayed_after_one_attempt_without_body_write`、`TrustedOutputTests.test_actual_v2_card_summary_is_accepted_without_rewriting`及`ResultPersistenceTests.test_real_confirmed_fact_adoption_uses_initializer_source_keeps_creation_and_increments_once` | 首轮实际通过；重复展示不写正文，短说明不重写，确认后正文合法采用 |
| `frontend`内`node --test tests/ai-read-owner.test.mjs tests/api-models.test.mjs` | 修复旧断言后24项通过，退出0 |
| `frontend`内`npm run build` | 类型检查及生产构建通过；补充空说明返回原文分支后再次通过。保留既有大包提示，不认定为构建失败 |
| `.venv\Scripts\python.exe -X utf8 tools/ai-service.py` | 离线准入检查通过，不读取密钥或请求Provider |
| `git diff --check` | 通过；已有CRLF转LF提示不属于空白错误 |
| `.venv\Scripts\python.exe -X utf8 tools/cleanup-test-artifacts.py` | JSON=0、screenshots=0，退出0；Markdown及正式输入保留 |

验证行为：有效卡片短说明可以落库和显示；重复原题直接显示，不再无进展拒绝；普通文本、多余字段、截断、refusal／工具式信息能够保留原文；有实际返回后不为格式问题付费重试；网络尚未返回内容时保留既有有限重试。原事实确认、取消、并发派发、SQL失败及提交回执丢失保护保持。未确认事实返回可见但正文版本不变；历史失败读取不创建消息。

## 4. 当前服务与数据

停止前8000归35852、5173归35092，无RUNNING／WAITING_USER。原后端退出并确认端口释放后，用`.venv\Scripts\python.exe -u -X utf8 tools/ai-service.py --start`启动；后端19440，创建时间本地19:33:02，startup complete。前端原服务保持，当前源码通过Vite提供。

GET8000及5173的`/api/v1/guide-runs/11`均200，success=true，状态仍FAILED；returned_responses包含13／14／15，完整content分别4135／4212／4215字符。5173代理需求3的消息及运行列表GET200。没有代替用户继续运行或把历史失败标记为成功。

重启和GET前后计数均为requirements=3、guide_runs=11、llm_uses=15、conversation_messages=26；需求3 CURRENT文档13的content_version=1。测试使用临时SQLite及本机受控HTTP返回，未请求真实Provider，未产生新业务AI调用。

## 5. 未覆盖

没有恢复全项目测试／验收，没有真实模型行为与新增计数观测，没有完整浏览器或视觉验收。前端展示依据类型／构建及读取生命周期专项，当前服务只用GET核对数据投影。新格式的只读回退没有可提交控件；正常结构卡片仍使用原回答控件。既有模型推理关闭和审计脱敏保持。
