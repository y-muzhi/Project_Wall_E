# V2.1输出合同接口绑定修复

日期：2026-11-18。接续用户“启用AI／先修复再重新验收”的目标。第二轮默认组60次已完成但37/60程序接受，23拒绝；当前新增实现/离线检查可以继续，第三轮真实调用必须另获明确授权，不恢复旧额度。正式设计不自动合并。

## 输入、交付与不变量

输入为v29/v30、Fixture v2及第二轮正常审计，保持旧资源/清单/两轮证据。交付为新v31/v32、区块引用类型及准确的两类ADD_STEP说明、受新release私有配置控制的供应方Schema约束、离线传输/历史还原/权限回归和新冻结输入。Schema210/r7、core/r54及正常数据不变。

不更换模型、密钥来源、温度、输出上限或取消/事务规则；不自动修复模型返回，不把文档身份展开成未读区块，不借旧技术准入放行新release，不设置HTTP/页面绕过开关。不冒充独立人工评价或真实供应方兼容通过。

## 核心改动

1. document_refs类型限定为本轮当前目标Revision的真实区块别名；ASSESS_STEP可空，空文档明确空列表。ASSOCIATE_CONTENT没有实际区块时请求材料，不构造文档级覆盖。
2. 明确普通formation_delta的ADD_STEP使用temp_ref及expected_results[].temp_ref；路线卡使用temp_step_ref及expected_results[].temp_result_ref。形状示例完整，不改程序所接受的字段。
3. 在新release增加私有model_transport描述，先只对DISCUSS启用json_schema/strict。CollaborationContext从已冻结的Canonical资源取原Output Schema，按声明版本生成供应方语法投影，并仅用实际Wire中的当前目标块绑定区块枚举；空区块时约束评估覆盖为空，并排除不可执行的关联变化。不读取当前库扩充枚举。
4. 供应方仅支持部分Schema约束，已确认的类型/属性/required/enum/const/本地引用及联合等用于生成约束；不支持的范围/长度/模式等保留在本地完整权威Schema，不能用投影替换本地验证。未知语法失败关闭，不能静默放开。原始Output与实际SDK request摘要分别审计，私有ContextBasis不作为输出schema发送。
5. ModelProfile模型参数及历史snapshot保持；只有冻结新release的上下文才附加response_format。旧release请求体没有新增字段，历史request恢复仍按原字节核对。
6. 首例兼容性必须重新验证：实际格式参数、返回结构、真实usage、framing与预算；文档不能当供应方证据。8项真实文本及1024余量暂不擅自改变；如果新接口字段导致计数偏差，按事实停止并修正对应新规则，不用放宽准入掩盖。没有真实许可前只做离线检查。
7. 后续付费执行器在首个确定的结构/权限/预算阻断时停止后续发送，60分母保留未运行项，不换样本、不重试。此为减少已知无法达标批次的额外调用，不把部分执行记整组通过；实际授权中明确该停止边界。

## 主要依据与证据边界

本地ModelProfile.request目前未设置response_format，而官方API提供json_schema与strict配置；语法约束不替代语义/权限校验，oneOf/allOf仍需本地严格验证。[官方结构化输出](https://docs.volcengine.com/docs/ark/structured-output-beta?lang=zh)、[官方Chat API](https://docs.volcengine.com/docs/ark/chat-api?lang=zh)。

官方模型列表列出当前deepseek-v4-1-flash-260910支持结构化输出；这是产品能力列表，不能代替本仓库模式、资源及计数兼容结果。[官方模型列表](https://ark.volcengine.com/region:cn-beijing/docs/model-list)。

实施前确认源码固定构建成员未包含ModelProfile/CollaborationContext/formation resource_schema，避免无必要改DDL或固定启动工具。输入/源码/资源稳定后重新冻结及完整复核；当前-02槽已结束，不在其运行中改代码。

## 实施结果（2026-11-18）

新v31/v32及Prompt v10、区块类型、冻结Schema到SDK约束、历史还原、首次拒绝停止和独立单次观察额度已实现。投影oneOf转anyOf，仅供应方语法层避免删除pattern后的分支重叠，本地完整oneOf不变。62项已分别通过（最终组61项，测试目录配置修正后单项1通过），两轮120原请求只读还原一致，两组各60/120冻结及全量重建一致。详见[验证](../../../verification/v2.1/ai-output-contract-binding-2026-11-18.md)。

第三轮尚无真实许可，默认首例观察上限拟1 Chat/2计数/139264 Token/0重试；独立观察即止，不默认继续59条。附加Schema实际计数兼容未知，失败不放宽旧门槛。v31/v32真实供应方及双人人工仍未完成，正式AI未启用；本迭代不合并主设计。
