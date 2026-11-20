# OpenAI真实通过及本地启用

日期2026-11-20（Asia/Hong_Kong）；HEAD a0f40592702cb702ed928849ac540479c22c224f，实际未提交工作区。用户要求先独立迭代后代码、保留DeepSeek，并明确授权验证通过后切换2.1。未提交推送、未自动合入正式设计。

## 真实执行

| 许可/槽 | 计数尝试 | 模型请求 | 实际结果 |
| --- | --- | --- | --- |
| 首轮compat-01 | 1 | 0 | 直连TRANSPORT_ERROR，无HTTP状态，停止 |
| 次轮compat-02 | 1 | 0 | 显式本机代理后HTTP400，当时未留具体错误，停止 |
| 第三轮首段compat-03 | 1 | 0 | HTTP400、invalid_json_schema、param=text.format.schema |
| 第三轮修复compat-04 | 1 | 1 | 原生计数、模型、完整本地结构及同release技术准入通过 |

各次0自动重试。第三轮用户明确允许计数参数错误修复后在总3计数/1模型内复验，实际2计数/1模型，余1计数未用，模型额度已结束，不再自动补发。四槽共4次计数尝试、1次模型；首轮不能推断供应方已成功接收。

成功源data/openai-compat-04/input.sqlite，LLMUse1：provider=openai，实际model=gpt-6.2-sol，call/validation均SUCCEEDED，finish_reason=stop。实际输入23108/输出416/合计23524 Token；整请求计数23108，gap0。合成document42仍空白/content_version1，Revision1，普通讨论未直接写正文。正常input.sqlite/count-audit及失败槽均保留。

供应方只给通用Schema无效解释；核对实际空白ASSESS.document_refs为array/enum=[[]]、无items。新投影明确items string/minItems0/maxItems0，精确保留[]，未知复合const/enum拒绝。实际新投影计数与模型均成功构成兼容证据，通用JSON Schema元校验不能替代。代理/有界错误诊断已修；不改DeepSeek、本地完整校验或业务权限。

新openai-v2冻结20文件，manifest3b10a730eb5fcd346cec68b163bc4a2ee9ef1023674e513a369616bedaeaa543，release0561b4fd08fed60d80378d9231f1fe84f078cd129b91f1872a9faa109954f014，Profile435677eaccadab44180c852a2e1fdfac5b0ec390bfdddbc17b78e3c72ab867cf。gpt-6.2-sol/medium为别名身份，不假称日期快照。旧openai-v1资源/历史投影及DeepSeekv37/v38保持，Schema210-r7/core-r54及固定构建源本次未改。

详情：[首轮及代理](openai-compatibility-2026-11-20.md)、[次轮及诊断](openai-compatibility-2026-11-20-v2.md)、[第三轮定位](openai-compatibility-2026-11-20-v3.md)、[修复成功](openai-compatibility-2026-11-20-v3-repair1.md)。

## 实际检查

此前原生五任务/六失败16项、生成修订2项、前端10项/类型/格式/实际模块/只读页面证据保留。旧共享组102通过/10子项/4旧初始化夹具失败仍按原结果，不恢复废弃初始化或冒充全组通过，见[离线记录](openai-integration-offline-2026-11-20.md)。

本轮代理/协议/计数/CLI29项通过14.31秒，独立DeepSeek隔离1项通过1.20秒、环境隔离1项通过；诊断30项通过15.55秒；上限CLI3项10.58秒；新投影/旧实际请求精确恢复/六Schema/原生生成修订/CLI24项89.29秒。组有重叠，不相加当唯一用例数。固定SQLite/quality_python/MockTransport/隔离临时目录，清理均True。

最终只读CLI带--database时发现catalog后才激活SQLite导致RuntimeNotAdmitted；已调整只读分支顺序，新解释器回归最终3项通过14.75秒、cleanupTrue。实际start分支原本即先激活，运行服务不受影响。正常库只读检查现在返回LIVE_VERIFIED/credentials_read=0/provider_calls=0/service_started=0。595 app格式、受影响Python F/I/B、git diff --check通过，Key文件Git忽略。源码整文件同目录临时+fsync+原子替换，不留测试JSON报告/原始日志/截图。

## 切换、数据和页面

切换前再次核对无RUNNING/WAITING，8001/PID28476确属本工作区ai-startup.py --start，才停止该旧后端。原approve_saved_call从compat-04导入同release技术证据，正常库effective current LIVE_VERIFIED、require_live通过；仅新增对应release准入侧文件，不伪造LLMUse或迁移数据库。

已隐藏启动data/service-runtime-v21/backend-openai-host.ps1，宿主337492；实际8001/PID58436、父278028，命令确认为tools/openai-service.py --start、同正常库、.env.openai.local、显式http://127.0.0.1:7897。密钥只加载后端，不进命令行/前端/文档。5174/PID311404保持。原DeepSeek宿主/凭据源/代码/资源保留，旧2.0不重启。

切换前后requirements、requirement_documents、revisions、guide_runs、llm_uses五表全行规范摘要一致，数量1/1/1/6/3，在途0。不能扩大为整个数据库所有运行元数据字节不变。没有重放用户失败Run或发送真实需求正文。

8001与5174的/api/v1/requirements均success=true/items1。切换后Playwright CLI0.1.24只读列表→需求1→进展Tab可见，pageerror0/业务writes0；外部及非GET/HEAD/OPTIONS拦截，浏览器临时清理True。没有为页面检查发送额外模型请求。

## 当前状态

2.1本地需求文档协作已切OpenAI：http://127.0.0.1:5174/requirements。默认无--database只读命令显示冻结资源OFFLINE_READY初态；正常库有效准入为LIVE_VERIFIED，请用--database检查实际启用情况。

仅证明同release单例真实技术兼容与本地启用，不能替代完整语义60/独立人工/长输出/整版正式验收。OpenAI Coding/Testing及页面模型/Key配置未扩展。用户可主动发起新业务，本轮不代重放或自动多发测试。服务保持运行；后续维护须核对当前PID/命令/在途，不照抄历史PID。
