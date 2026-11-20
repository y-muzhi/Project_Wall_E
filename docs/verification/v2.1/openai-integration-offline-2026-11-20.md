# OpenAI独立接入离线验证

日期：2026-11-19—20（Asia/Hong_Kong）；Git HEAD：a0f40592702cb702ed928849ac540479c22c224f。检查实际未提交工作区；本次新增独立供应方，既有2.1实施改动保留，不自动提交、推送或合入正式设计。

设计依据：[OpenAI独立迭代](../../iterations/pending/v2.1/WALL-E.OpenAI官方接口独立接入迭代_V_2.1.md)。先完成迭代文档，再实现Profile、Responses请求/响应、严格输出投影、整请求计数、共享C01/C07和准入/审计、独立资源、只读检查/观察/启动入口及请求详情。

## 实际结果

| 范围 | 命令或执行依据 | 实际结果 |
| --- | --- | --- |
| 首批协议/旧Profile审计 | test_openai_primitives.py + test_model_profile_audit_data.py | 24 passed、10 subtests passed；0.89秒；临时清理True |
| 原生OpenAI完整执行 | test_openai_execution.py，Schema210真实C01/C07、HTTP MockTransport | 修正审计配置问题后16 passed，192.40秒；两种正文×五任务及六失败分支；临时清理True |
| 新旧共享回归 | 固定SQLite tools/python-v20.py → tools/quality_python.py，下列9文件，-q -p no:cacheprovider --tb=short --basetemp临时目录 | 102 passed、10 subtests passed、4 failed；565.62秒；临时清理True。四失败均旧初始化夹具前置失败，详见下一节；不标全组通过 |
| 原生生成/修订 | 同上隔离运行test_openai_writes.py | 首次两项夹具把业务文档类型写成存储枚举DESIGN，按既有契约改为design后2 passed，55.49秒；生产无改动；原保存链各一Revision/一CONTENT_COMMITTED，其他文档保持；临时清理True |
| 前端请求详情 | node --test frontend/tests/model-calls.test.mjs（原项目方式） | 10 passed；整请求1项与原8项诊断互斥，未伪造分项 |
| 前端类型/格式 | npm run typecheck；npm run format:check | 均通过 |
| 后端格式/静态 | python -m ruff format --no-cache --check backend/app；修改的28个Python文件ruff check --no-cache --select F,I,B；git diff --check | 594 app文件格式通过；全部修改文件F/I/B通过；差异检查通过 |
| 默认准备入口 | .venv/Scripts/python.exe -B tools/openai-service.py | OFFLINE_READY；credentials_read=0/provider_calls=0/service_started=0 |
| 开发模块 | 5174只读GET /src/api/model-calls.ts 与 /src/guide/model-call-view.tsx | 实际返回15001/115720字节，modelCallDetail/ModelCallsProvider导出及新计数标识/整请求文案均存在 |
| 真实页面只读 | 已安装Playwright CLI 0.1.24；只放行本机GET/HEAD/OPTIONS | 需求列表→需求1→进展Tab可见，pageerror0/业务writes0；临时浏览器目录清理True |

共享回归文件：backend/tests/formation/test_openai_execution.py、test_openai_primitives.py、test_openai_counting.py、test_openai_service.py；backend/tests/infrastructure/test_model_gateway.py、test_model_profile_audit_data.py；backend/tests/guide/test_v15_counting.py、test_v15_execution.py；backend/tests/formation/test_v21_live_fix_examples.py。

Python执行统一quality_gate.environment，禁止外网、用户data及本地密钥读取，SQLite只能位于本轮TemporaryDirectory。原始输出仅在内存/工具输出，没有新增测试JSON报告、原始日志或截图；本次未真实调用供应方。首次本机模块GET在默认权限被WinError10013阻止，随后同一只读GET通过获准权限完成，不属于模块缓存故障。

## 失败定位及边界

1. 首轮原生C01审计失败：通用脱敏器按原规则删除reasoning键，误删固定request.reasoning/profile.reasoning配置。已仅在这两个严格验证路径恢复固定effort，其他私有reasoning_content/encrypted_content/凭据继续脱敏；计数及模型请求可逐字重放，后续16例完整通过。没有弱化全局脱敏。
2. 一个计数原语测试缺失诊断texts夹具，已补齐；后续共享回归中的该专项通过。Ruff循环闭包绑定亦已修正。
3. 共享回归四项失败均在test_model_gateway.py通过旧AuditRepositoryTests→RecoveryTests→CreateRequirementTests创建旧初始化需求时发生，尚未进入模型传输。实际诊断返回INVALID_INPUT：template_key/template_version/initialization_mode为UNKNOWN_FIELD。现行需求创建已取消这些旧参数；此为旧版初始化夹具和当前业务入口不相容，未为其恢复第二套旧初始化流程，也未把四项写成通过。一次临时诊断还因导入unittest类触发了旧创建用例收集，确认同一旧参数原因；临时目录清理True。
4. 因上述旧夹具setup提前失败，曾产生临时lock文件的析构警告；外层隔离目录最终清理True。现行DeepSeek的v15 counting/execution及v21修复样例均在共享组通过；这些通过不能替代原四项旧版初始化场景。

## 固定资源与服务现场

OpenAI资源backend/resources/openai-v1，共20文件；manifest SHA256：9ddea44727ed60fe6e792708b3f109c7acbd33cb279c5e4e43c446a7dd6a9880；release：32999ee29f7253d93104e42801d0c55e98d4ca13815e6d9ebe2be2bd872a1df7；Profile：435677eaccadab44180c852a2e1fdfac5b0ec390bfdddbc17b78e3c72ab867cf。旧v37/v38、Schema210-r7/core-r54及固定构建源未在本接入中修改；执行专项已按现行固定Schema成功加载。

本轮没有启停用户服务。最近只读现场：5174/PID311404，8001/PID28476；正常库1需求/1文档/1Revision/6GuideRun/3LLMUse，在途0。较历史3Run/0Use已变化，应视为用户现行业务现场，不回滚或重放。浏览器可读不等于后端已载入本批代码；现有8001仍为原DeepSeek宿主。最终供应方服务启用前，仍须核对在途、同release准入及统一加载代码，不能凭旧进程宣称OpenAI已启用。

.env.openai.local已建立且git check-ignore命中，仅返回路径/存在及忽略事实，不把密钥打印或写入记录。用户截图未看到时已提供2.1独立工作区绝对文件链接；同名原项目目录不能代替本工作区。尚未收到“已填好”确认。

## 未执行

真实OpenAI模型/计数调用均0；账号模型权限、接口实际兼容、真实计数与usage吻合尚未验证。OpenAI技术状态仍OFFLINE_READY，未向正常库导入LIVE、未切服务、不声称完整产品验收。真实验证应仅用固定合成电影样本和项目通用协议/模板/输出Schema，官方/v1/responses/input_tokens与/v1/responses，1模型/最多3必要计数/0重试；不再增加额外费用预算，仍须明确该次外发范围后执行。用户本地Key尚待就绪；DeepSeek逻辑及默认启动方式保留。
