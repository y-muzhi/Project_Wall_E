# WALL-E OpenAI官方接口独立接入迭代 V2.1

日期2026-11-19，状态IMPLEMENTED_LOCAL_TRIAL_ENABLED，正式前后端设计暂不合并。用户要求新增OpenAI、保留DeepSeek，沿先文档再代码流程；已确认官方api.openai.com，模型由代理核对推荐。2.1 DeepSeek试用已运行，当前任务不擅自切换或重启它，不复用旧真实调用许可。用户要求不再设置额外费用预算，不删除程序原生输入/输出/容量与取消保护。

## 1. 输入、范围和模型选择

复用现行V2.1后端/前端DRAFT契约、原C01/C07/Formation对象、数据库Schema210-r7/core-r54及现有ContextBasis/资源冻结/审计机制。新增供应方技术适配，不再建立第二套文档业务流程、实体或HTTP写接口。本轮没有页面模型/密钥配置需求，先提供独立本地配置及可核对启动入口。

推荐模型gpt-6.2-sol，reasoning.effort=medium；官方当前仅提供该模型ID，不能伪称有固定日期快照。Profile标为别名身份，本地Profile版本固定；若供应方以后换别名模型，实际响应model必须匹配当前批准身份，否则拒绝。OpenAI与火山凭据不交叉回退。

## 2. 请求与凭据

独立Profile openai-sol-v1，provider=openai，固定https://api.openai.com/v1/responses；密钥OPENAI_API_KEY来自用户本地指定文件或后台环境，不进入前端/文档/快照。现有DeepSeek配置WALLE_MODEL_API_KEY、默认选择及历史Profile请求字节保持。仅显式选择新Profile才使用OpenAI。

实际请求使用Responses原生input的developer、user两项，完整system/Wire分别保持原文；text.format=json_schema/strict绑定该release对应的输出Schema，reasoning.medium、store=false、stream=false、truncation=disabled，无工具/previous_response_id/conversation或后台请求，不把私有ContextBasis/权限依据发给模型。使用原程序输出上限8192及原上下文硬上限，不新增费用预算。

独立OpenAI HTTP适配器沿httpx、trust_env=false/不跟随重定向/0自动重试/每次独立连接，取消关闭本次连接但不保证供应方已停止计算。保留完整真实OpenAI原始返回，不伪装成火山chat.completion；业务解析使用明确的供应方提取器，从唯一completed assistant/output_text提取JSON，拒绝拒答、incomplete、工具输出或多消息歧义，真实usage包含reasoning输出。

## 3. Schema和资源隔离

新增命名资源openai-v1，与v37/v38等DeepSeek目录均独立；后端加载器固定manifest原SHA、release与Profile摘要，并按历史resource_ref精确恢复。默认DeepSeek仍v37/v38。新资源的Prompt/Guide/Structure/Output本地权威合同复用现行内容，不扩大读材或文档写权限。

OpenAI只发送受支持语法投影：根解析为object，所有对象additionalProperties=false、required完整，oneOf按供应方语法联合anyOf，已知不支持条件/allOf中的条件关联保留本地权威校验，未知组合语法失败关闭。引用与实际当前区块枚举从冻结Canonical/Wire派生，不读新数据库扩展；空块ASSESS覆盖[]/排除ASSOCIATE_CONTENT保持。离线验证根/嵌套/属性/枚举容量，超供应方限制拒绝派发，不静默降级json_object或自由文本。

## 4. 原生整请求计数

OpenAI使用https://api.openai.com/v1/responses/input_tokens，按同一实际input与text.format/schema及计数端点支持的相关字段提交完整请求投影，一候选一计数，不沿用火山8项Tokenization或假造Token数组。

新独立不可变OpenAI计数凭据记录endpoint/model、实际计数请求摘要、对应完整推理请求摘要、真实response.input_tokens原文与request_tokens，原8项文本仅作为上下文诊断，不假填8个Token数。接受候选须整请求Token加原输出上限满足程序原上下文/总量上限；计数不明确、凭据归属/摘要不符、真实usage不匹配立即停止。OpenAI不使用DeepSeek的经验framing预留。裁剪仍沿full→no-history→required的原确定顺序，最多原三候选、不按正文截断或隐藏重试。

CountingJournal按同一C01/C07路径保存新供应方完整计数请求及真实凭据；原火山journal字节/格式保持。保存、恢复、真实usage和请求详情均明确整请求计数，避免把它塞进旧system/Wire分项或伪报0 Token。

## 5. 准入、审计和兼容

沿用CollaborationAdmission原文件/原始证据/锁/原子保存骨架。新增OpenAI子类仅覆盖供应方真实计数/usage证据解释与撤销检查，用工厂按冻结release选择；不改固定core构建源collaboration_admission.py，不为技术差异复制业务流程。OpenAI Admission字段用request_input_tokens/count_gap表示整请求计数，不伪装原system/user分项。初始OFFLINE_READY；真实计数及推理原审计通过后才能导入对应release的LIVE，不能借DeepSeek证据放行。

LLMUse.provider、snapshot、request、response、usage、finish_reason均真实供应方含义；API读取旧记录继续按旧Profile恢复，原火山解析/历史字节不改。公共错误码仍沿原AUTH/CONFIG/MODEL/OUTPUT等路径，凭据回显或不明供应方响应失败关闭，取消/晚到/事务保护不变。新供应方Provider辅助只作为共享技术边界，不新增公开模型选择请求字段。

## 6. 实施批次和完成条件

A：完整独立文档→Profile/请求/结构投影/响应提取/计数凭据与适配器，MockTransport离线验证。
B：接原C01/C07、计数journal/审计/历史恢复/usage/准入工厂、独立资源、请求详情，核对全部正常生产调用方，不能停在未接入组件。
C：独立本地启动配置/只读准备及隔离真实观察入口，DeepSeek回归与OpenAI完整五类任务C07、取消/失败/历史/资源隔离专项。检查只留Markdown，测试原始JSON/日志/临时数据库清理，正常业务审计依法保留。
D：用户本地凭据与真实观察另依当前范围确认，不增加额外费用预算/反复预算询问；没有真实新供应方授权前不读取密钥外发或试发API，也不替换当前试用服务。需要外发时明确官方目的地、合成样本与项目通用协议范围、有限次数及0重试。没有真实证据不声称官方API已可用。

## 7. 来源与证据边界

- [官方模型](https://developers.openai.com/api/docs/models/gpt-6.2-sol)：支持结构化输出，reasoning不能none。
- [模型选择](https://developers.openai.com/api/docs/guides/model-selection)：Sol medium作为常规API工作起点。
- [Responses](https://developers.openai.com/api/reference/resources/responses/methods/create)：原生请求/状态/usage。
- [整请求计数](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count)：请求格式与原生input/输出Schema一同计数。
- [结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)：object根/required/封闭属性与支持语法。文档只能指导实现，不能作为该用户Key/模型权限/真实兼容证据。

设计来源/已读：本轮已读AGENTS、当前断点、模型/网关、计数/Journal、C01/C07/审计解析、Observation/Admission、现行资源结构与官方对应资料；未启动全项目重测/真实请求/用户服务切换。后续每批记录实际文件/结果及未覆盖，不提交推送。

## 审计配置补充

现有通用脱敏器删除reasoning键以保护模型私有内容。OpenAI request.reasoning仅为固定effort配置，应只在已验证的request.reasoning及profile.reasoning精确路径恢复本地固定配置，保持可重放请求；不取消全局reasoning_content/encrypted_content/凭据脱敏。计数准备及模型审计采用同一严格路径，其他字段若脱敏后改变请求仍在I/O前拒绝。响应原生对象继续按原脱敏保留，不伪造火山envelope。生成/修订等原根联合仅在供应方语法层投影到共同九字段object，各字段候选用anyOf；原类型关联和分析结论限制继续由完整本地Schema执行，不授予更多业务行为。

## 2026-11-20实施状态

A/B/C已实现并完成所列离线检查，D真实接口尚未执行；证据见[本批验证](../../../verification/v2.1/openai-integration-offline-2026-11-20.md)。保留四项旧初始化夹具失败的真实结论，不为其恢复废弃流程。用户本地Key待填写确认，未切服务或正式合并。

## 2026-11-20单次连接失败与本机代理修复

新槽openai-compat-01已执行：1次计数尝试、0次模型、0自动重试；计数TRANSPORT_ERROR/HTTP状态未知，停止，未切用户服务，不能判断Key/模型权限。原计数审计和隔离数据库保留。只读发现Windows系统代理开启，127.0.0.1:7897；目前适配器明确trust_env=false直连，因此代理未被使用。这是有证据的路由差异，不能仅据此认定全部根因。

新增显式OpenAI专用OPENAI_HTTP_PROXY及CLI --proxy，只允许无账号密码/路径/查询/片段的HTTP回环IP+明确端口；不自动读取Windows代理/PAC、HTTP_PROXY/HTTPS_PROXY等，不改DeepSeek。HTTPX在本机HTTP代理上为固定官方HTTPS目的地建立CONNECT，继续TLS证书验证、0重试、无重定向；计数和Responses用相同工厂。代理不是新供应方地址，不更改原生请求/资源/Profile或准入证据字段。默认仍直连，未知代理失败关闭，不回退别的路线/自动补发。

只记录固定代理地址和安全异常类型，不输出凭据/请求正文/异常自由文本。离线核对显式/默认/拒绝配置、两适配器相同代理、旧DeepSeek隔离；本次失败许可结束，第二次真实验证必须单独明确本机代理及相同官方目的地/合成载荷/次数。通过后的服务切换许可仍保留，但不得先切未通过的新供应方。

## 2026-11-20第二轮HTTP400与计数失败诊断

compat-02经用户明确授权通过127.0.0.1:7897执行后，1计数/0模型/0重试，HTTP400；停止，不切服务。原生错误响应未被适配器保留，只知道状态码，不能从现有审计还原拒绝参数或断言原因；不据猜测变更请求、模型、Schema或计数口径。官方计数参考当前列明reasoning/text/truncation，现有字段名静态可对照，不代表具体Schema或账号已通过。

修复已知诊断缺口：OpenAIInputCounter在收到非2xx状态后，复用既有Tokenization的有界_http_error脱敏投影，仅将分类换为OpenAI分类；保存原code/param/截断脱敏message/request_id到原计数Journal的provider_error，不新建日志/错误数据实体。最多16KiB读取，原凭据全量脱敏后再截断2048字符，非JSON/过大/读失败保持原HTTP状态，0重试；不输出供应方自由文本到控制台/验证记录。成功计数响应、实际请求/计数摘要、资源/Profile和业务流程不变。后续一次若再400，先从正常私有审计给出有证据的拒绝参数，不猜测试错。

观察CLI增加--count-limit 1/2/3，只降低原上限，便于用户另行允许明确参数修复复验时按本轮剩余次数派发新槽；没有自动重试/自动修复循环。诊断修复30项及CLI3项通过，详见第二轮报告。

## 第三轮明确Schema拒绝与空数组投影

compat-03第三轮首个观察：1计数/0模型，400 invalid_json_schema / text.format.schema；该轮还剩2计数/1模型，用户已明确允许计数参数错误修复后在剩余次数内复验，不额外请求预算或重用旧槽。错误只给通用Schema无效，没有具体路径；实际发送Schema的空白ASSESS document_refs节点为type=array/enum=[[]]且没有items，虽通用JSON Schema元校验通过，但不符合当前供应方结构语法的明确数组元素定义方式。不能把通用元校验当供应方支持证明。

新增openai_strict_subset_v2：仅把已知type=array,const=[]投影为type=array,items={type:string},minItems=0,maxItems=0，精确保留空数组集合；其他未知复合enum/const拒绝，不放松本地规则。发布新openai-v2资源，旧openai-v1及三次原始计数请求保持；历史投影v1仍按原字节恢复，不用新算法重写旧证据。默认OpenAI选v2，DeepSeek不改。完整新Schema离线核对实际空白/非空目标及六操作、无复合enum/缺items，之后才在剩余次数内新槽复验。此修复是与明确拒绝一致的已知语法缺口，是否足以解决仍由下一真实计数证明。

故障定位可以在工具内读取正常私有审计的已脱敏有限解释以核对拒绝原因，不另导出完整响应/日志，Markdown只记code/param/安全摘要；之前“不输出供应方自由文本”约束面向产品控制台及验证记录，不能阻止本轮必要的私有审计阅读。

## 最终接入状态（2026-11-20）

openai-v2真实单例通过，按授权启用正常2.1本地服务。见[启用结果](../../../verification/v2.1/openai-enabled-2026-11-20.md)。此前失败原样保留，不把单例写为整版验收。最终只读CLI先激活SQLite再加载catalog，新解释器回归通过；生产start原本正确。正式设计不自动合并，DeepSeek保留。
