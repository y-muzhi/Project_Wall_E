# WALL-E V2.0 受控模型协议与预算准入迭代

日期：2026-11-03（Asia/Hong_Kong）；编号M20-MODEL-01；对应Q20-MODEL；状态：设计已定／待协议及渠道验证，保留pending。本文记录选择、依据及差异；共同契约仍归后端草稿，页面归前端草稿，不建立第三份现行共同规格。

## 1. 任务、基线与边界

用户要求逐项处理未定项并继续完成。前三项OpenCode v1.19.5、允许参考仓库开发规范及Windows内置隔离保持。本单元选择可复用现有渠道的首期模型协议，不新增产品流程或供应商选择要求。

起点后端0.5-draft-5／前端0.4-draft-4，均DRAFT。只修改V2.0 Markdown并静态核对官方源码、文档及现有模型／审计代码。不改产品代码、模型配置、秘密、资源、数据库、原汇总或V1.5正式设计；不安装／运行OpenCode或Guard，不发模型／计数请求，不运行模拟服务、产品测试、构建、浏览器，不启停用户服务或提交推送。发布价格版本和可执行配置仍须实际准入证据。

## 2. 已核实的缺口

- 现有ModelProfile／ModelGateway面向文档：固定system＋JSON用户包、非流式和文档输出校验。复用身份、密钥来源、HTTPX及LLMUse，不复用文档Wire或把工具调用当文档JSON错误。
- 固定OpenCode提交的所有Provider请求带x-opencode-session-id，但模型headers及插件可覆盖；普通请求头不是独立身份凭据。原生会话元数据、受管来源与当前执行窗口必须共同核对。
- 原生AI SDK单次stream默认maxRetries=0之外，processor仍有高层重试；标题生成也可额外调用模型。只关闭后端HTTP重试不足以保证预算边界。
- 现有Tokenization只证明文本计数，未证明messages、工具定义和协议封装的精确计数。不能把它当完整编码输入上界。
- 累计流式usage、请求结束时的价格时段、缓存输入子集和缺失用量分别处理；HTTP错误、取消或断流都不证明免费。

## 3. 采用的设计

### 3.1 OC20-MODEL-1与渠道

首期固定火山方舟北京Chat Completions文本／function-tools／SSE协议；沿现有ModelProfile及WALLE_MODEL_API_KEY后端来源。候选沿已有deepseek-v2对应deepseek-v4-1-flash-260910，不自动升级模型。8192输出上限、temperature=0、thinking.disabled沿原快照；不是已完成渠道验证或已发布价格。

现有文档Profile不可变快照不改，编码在ExecutionProfileVersion.models内增加协议绑定。原生Provider为walle，使用固定运行包内@ai-sdk/openai-compatible；CODE与COMPACTION分别使用walle-code及walle-compaction。两项config model.id也固定为各自别名，避免原生api.id提前变成真实模型而丢失用途；后端才映射真实模型。默认两别名引用同一已批准Profile，不自动选择small／latest模型。

私有baseURL为http://127.0.0.1:{port}/internal/code-model/{binding_id}/v1；只接收POST /chat/completions，直接HTTP/1.1连接，不经反向代理或HTTP/2复用。供应商请求固定到现有北京/api/v3/chat/completions；不得转发客户端URL、认证、组织、代理或身份头。模型入口不是公开业务API，浏览器没有调用权。

### 3.2 归属与执行窗口

来源链为：短期实例Bearer＋私有binding → Guard核对当前TCP连接真实来源 → 固定原生会话头 → 持久ExecutionSession及其model_window。不从请求正文task_id、当前角色或相同文本猜归属。

Guard只读VERIFY_MODEL_SOURCE增加到前项OS协议，输入为当前受管绑定、后端实际accept连接的IPv4／IPv6五元组和原请求nonce；核对ESTABLISHED连接、来源PID、创建时间、实际受管OpenCode根进程句柄、LPAC及Job。PID表查询本身不是充分证明；还须阻断任务子进程向根进程注入、借用令牌／句柄或转发套接字。证据在实际发送前复核，连接关闭、复用／不唯一或身份边界未证明就拒绝。该组机制是本方案组合设计，不是OpenCode已提供或本机已验证的安全能力。

model_window随原START／RESUME／REPAIR等执行操作持久化，绑定该operation_id及预分配native_trigger_message_id。原会话／消息确认前只在queue_wait_seconds内排队，绝不先发供应商。问答／权限子操作不覆盖外层执行来源；窗口关闭／旧代次／未登记原生子会话均不发。每会话至多一笔在途模型请求；未知费用处理后也不因迟到消息自动开新窗口。

检查脚本不能借实例密钥或伪造会话头冒充OpenCode根进程。首期普通检查不调用真实模型；需要真实模型的检查必须先定义独立可验证来源和授权，不在本协议下偷偷放行。文档移交仍归GuideRun，不重复扣代码预算。

### 3.3 请求、原生附加调用与重试

保留真实messages／tools／tool_choice和工具历史，不重包成文档JSON。只接受已列明的文本及function工具字段；图片／音视频／Responses／远程内置工具／显式缓存创建不在首期范围。未知字段明确拒绝；不静默删掉工具或改变参数。

实际供应商请求固定stream=true、stream_options.include_usage=true、service_tier=default、n=1、thinking={type:disabled}、temperature=0及已批准max_tokens。缺省由程序补齐，冲突拒绝；原生max_tokens只能小于等于绑定和任务授权上限。主辅Profile、模型能力及价格全部在发布配置时登记。

程序创建原生会话时指定非默认title，防止额外标题模型调用；压缩Agent显式绑定COMPACTION，所有压缩调用同样预留并计数。不增加隐藏规划／审阅或子Agent通道，不谎称原生循环完全没有自动重试。

后端供应商HTTP重试0。一笔请求一旦已发送而结果／用量不明，先原子关闭模型窗口并保留预留，再结束本地响应；原生自动重试最多命中本地关闭的入口，不能产生第二笔上游费用。本地预算／控制拒绝采用固定非重试4xx及稳定错误文字，不把上游5xx、429或可触发原生字符串重试的原文直返。真实新请求重新分配call_no、LLMUse和预留；相同正文不是幂等键，不能凭正文填写retry_of。

### 3.4 流式响应和审计

LLMUse继续是唯一实际调用账；新增按(llm_use_id,seq)唯一的响应帧子表，不另建CodeModelCall账。实际请求4MiB上限，单SSE帧1MiB／每调用响应16MiB上限；均先解码并验证有限文本／JSON结构，再按容量保存。请求过限在发送前拒绝；响应超限、审计不可写或断流发生在发送后，保留已得内容并标INCOMPLETE／UNKNOWN，不能截断后声称完整。

SSE逐帧有序保存脱敏审计后转发，工具id／index／name及arguments增量不重排。choices=[]的usage帧合法，tool_calls也是合法结束原因；不得按文档Schema解析。缺[DONE]不补造成功。只有结束事实、可靠用量及实际价格条件齐备才完成结算，输出length只表示截断，不代表任务完成。

usage为累计值，不按帧求和；以最后有效完整usage核对前面累计值，重复相同帧不重复计费，回退／冲突标DISPUTED。cached_tokens包含在prompt_tokens内，reasoning_tokens包含在completion_tokens内；缺字段保留null，不补0。审计只保留允许内容和思考Token数量，不保存私有思考链；凭据沿既有脱敏。capture_status明确FULL／REDACTED／INCOMPLETE；脱敏后的审计不声称字节级原始副本，转发的工具参数不因审计脱敏而被改写。

取消后仍以原LLMUse关联迟到费用，call_status=CANCELLED不改回成功，费用补记不恢复执行。来源不明的账单不能平均摊到当前会话。

### 3.5 预算和价格

每次先事务性保留LLMUse、发送资格及CodeTaskReservation，然后在发送边界再次核对窗口／停止／代次。首期不自动调用付费Tokenization；按已验证模型可计费输入上界I_cap与固定输出上界O_cap，乘可能适用的最高单价预留。输入完整上界必须覆盖所有消息、工具、封装及可计费拒绝场景；没有供应商可证明上界便不准入。现有文本计数不能降低该值。

~~~text
R = ceil_micro_CNY((I_cap × max_input_price + O_cap × max_output_price) / 1000000)
~~~

max_input_price覆盖输入分档、普通／缓存输入的较高值；max_output_price覆盖适用输出分档。价格时段取请求完成时，预留覆盖所有可能完成时段，不只看发送时低价。首次方案只采用标准按量文本工具调用、隐式缓存，不创建有持续存储费用的显式缓存；若实际账户另有计费维度，必须纳入可证明上界或拒绝准入。

ModelPriceVersion包含渠道、实际模型／账户计费范围、service_tier、时区／时段与分档、有效期、取整、来源及核验时间。网站公示价是研究来源，不代替当前账户可采用价格；没有可靠有效价不准入。保守预留可能高于实际用量，应明示原因，不显示成实际花费。

只有可靠usage及适用价格可得才按真实输入／输出及缓存子集核算；未命中与命中输入分开计价，不重复加缓存。跨无法判定的价格边界保留UNKNOWN；账单证据可提升settlement_basis=PROVIDER_BILL，不把VERIFIED_USAGE计算值叫供应商最终账单。事实超预留保留差额并封闭后续调用，不修改价格或Token掩盖。

已发错误／超时／取消不释放预留；只有确证NOT_SENT才释放。max_model_requests为已发、未知及已预留发送名额之和的上限，未发送释放名额但不回收call_no。重新打开HELD窗口必须来自明确控制操作且已核清原费用／可用额，不自动重放旧HTTP。

## 4. 影响、未采用方案与映射

| 项目 | 采用位置 | 状态与验证边界 |
| --- | --- | --- |
| 原生协议、别名、用途及标题／压缩 | 后端OBJ-CODE-POLICY、APP-CODE-MODEL、第7.5 | 设计已定；需固定运行包协议证据 |
| 来源证明与执行窗口 | 后端OBJ-CODE-EXECUTION、APP-CODE-MODEL、第7.3／7.5 | Guard新增只读动作未实施；不得降级只校验请求头 |
| SSE、审计及LLMUse复用 | 后端OBJ-CODE-USAGE、查询／存储、第7.5 | 不套文档解析；实际渠道及容量故障待验证 |
| 金额、最高价预留、未知与迟到 | 后端OBJ-CODE-USAGE、第7.5、TC20-53—60 | 未发布真实价格；未执行付费计数或模型 |
| 页面用量与费用说明 | 前端BND-CODE-USAGE、TC-FE20-41—43 | 不新增模型入口或自动恢复按钮；浏览器待实施 |

不采用：只凭实例密钥／请求头归属；复用文档JSON封装；隐藏辅助模型；把SDK重试0说成全链无重试；按历史均值或普通文本计数硬控预算；按发送时最低价预留；逐SSE帧累加累计用量；错误或取消自动退款；证据缺失填0；自动重放和自动恢复旧会话。原Windows迭代保留原字节，本迭代明确追加来源核验条件；前项六动作记录是当时方案，当前草稿增加VERIFY_MODEL_SOURCE。

## 5. 资料与实际已读范围

读取日期2026-11-03。固定提交810c0eba1a7348036f8bdf61e6632d0c36c6876c：

- [请求准备与会话头](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/llm/request.ts)、[AI SDK适配](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/llm/ai-sdk.ts)、[LLM入口](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/llm.ts)。
- [Provider加载](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/provider/provider.ts)、[高层重试](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/retry.ts)、[Processor](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/processor.ts)、[压缩](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/compaction.ts)、[Prompt及标题](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/prompt.ts)。
- 包声明采用ai 6.0.168／@ai-sdk/openai-compatible 2.0.41；[原生补丁](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/patches/%40ai-sdk%252Fopenai-compatible%402.0.41.patch)将SSE error对象保留而不是仅message。后续协议试验须以运行包及该补丁为准，未全文审计全部AI SDK。
- 方舟[Chat API](https://docs.volcengine.com/docs/ark/chat-api?lang=zh&redirect=1)核对function工具、SSE结束和usage；[模型列表](https://console.volcengine.com/ark/region:cn-beijing/docs/model-list)核对现有模型仍列出，不选择新版本；[价格](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh&redirect=1)核对分档／完成时段；[缓存](https://docs.volcengine.com/docs/ark/context-cache?lang=zh)区分隐式命中与显式存储收费。未访问账户账单、凭据或发API。
- Microsoft官方[GetExtendedTcpTable](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable)及IPv4／IPv6 OWNER_PID结构核对可用字段；网页读取受限时查官方[文档源](https://github.com/MicrosoftDocs/sdk-api/blob/docs/sdk-api-src/content/iphlpapi/nf-iphlpapi-getextendedtcptable.md)。该API是来源证明的一部分，不能独立证明完整安全边界。
- 本地已读model_profile.py、model_gateway.py、tokenization.py、audit_data.py及相关LLMUse查询／取消路径；未读秘密配置／数据库，未修改这些源码。其原模型快照和4MiB审计上限不能证明编码流式兼容。

## 6. 接续与完成条件

本轮静态记录另存[模型协议设计核对](../../../verification/v2.0/model-contract-design-2026-11-03.md)。前后端目标场景只登记不执行。Q20-MODEL转为设计已定／待协议及渠道验证；可执行配置仍ready=false，不能用本轮网页／源码阅读替代模拟协议、Windows来源证明或真实渠道收费证据。

下一项Q20-CONTENT：私有对象格式、固定清单、路径／特殊文件、源目录并发读取、原子发布及恢复。先独立迭代、再同步DRAFT。真实调用、安装／环境试验及产品实施均按后续明确授权办理，不因本单元自动开启。


## 本地模型入口与原发送准备（2026-11-09）

专用回环入口以实际 accept 和原 Guard 证据绑定连接。QUEUED 只允许有限等待原消息确认，费用预留和供应商请求只消费 OPEN。请求接受固定的文本／function-tools 契约，保持原历史关联和工具参数字节。程序从已核定的完整输入上界、原模型／授权输出上限和总上下文同时核对容量。拒绝原生 SDK 兼容层外的请求能力。绑定配置中使用实例专用短期凭据及回环基址，供应商密钥只由后端读取。原请求与已归一化实际请求进入同一个原 LLMUse 审计快照，先持久保存发送名额和费用预留，之后再核对原连接及窗口。

### 2026-11-09 原调用公开读取及预算等待

API66 摘要只读取原调用、会话和原预留的归属，按开始时刻及 ID 倒序分页。API67 选定原调用后读取原脱敏快照及已有帧，不返回私有来源证明和部署准入引用；帧缺失标记不完整。前端按原读取表现费用和传输状态、原生／发送请求及实际响应，可选择格式、搜索和复制。

预留不足或请求名额耗尽时，在确认原窗口仍开放的短事务中封闭该窗口，登记来源为本窗口原操作的 BUDGET 等待。未发送的拒绝不创建 LLMUse 或扣款。已发送但结果或费用未知时，以原 LLMUse 登记 MODEL_RESULT 等待；确实超预留时保留真实差额并登记 BUDGET 等待。停止已抢占则只补原调用账，不重新置等待；已核实终止将原等待事项按原终止操作关闭，费用记录保留。阶段静止、增加预算和恢复按原业务能力后续接续，不能借本次等待改造重发旧请求。

### 2026-11-09 追加预算和明确继续的实施边界

API40 接收正安全整数控制版本、人民币新总额及非空说明，同一幂等事务保存新金额、版本和 TaskView。预算理由仅为原命令记录。调额保留已核算及原预留、原等待、有效授权、模型窗口、工作区和原调用。未启动的调额版本由原 C40 回执证明，后续启动与空范围停止继续按真实原操作和所有分配记录核对。

API36 的首个正向分支针对同一任务、原 BACKEND 会话和已核清的模型等待。原控制事务固定原操作、等待项和代次，原生发送前复核有效授权、实际预算、原工作区／会话、启动和停止屏障。仍在执行时只观察；需要继续消息时仅在旧活动可核清后使用新固定消息 ID，并在可靠查回原消息后开放该窗口。旧调用或旧消息不重发，结果未知保留原继续操作及原意图。真实供应商、Windows 部署及实际账单另取验证证据。

### 2026-11-09 原操作历史读取

执行页从操作历史入口读取当前任务的 API42，选择一项时通过 API43 核对同一任务及操作。列表和详情共用 API17 的原步骤投影，保留原接受和失败事实。按现行分页规则处理空页、失败和跨任务归属；读取不触发后台动作。
