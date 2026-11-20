# V2.1结构化输出计数补齐迭代

2026-11-18。接续用户先修复再验收并启用AI的目标；单次兼容观察已使用1 Chat/1计数，0重试，额外调用授权现已用完。先离线修复，不再发模型或计数请求，正式设计不自动合并。

## 事实与原因

v31观察实际输入26483、输出864，总27347 Token；原system计数15049、Wire1002，差10432，超过旧1024余量。请求SDK结构参数已被接受；原完整Output Schema及basis_ref的只读事后核对通过，但程序在实际usage门槛处停止，validation_status为NOT_STARTED。执行器通用标签STRUCTURED_REJECTED不能解释成JSON Schema不合法。原正常审计与报告保留，不回写成通过。

新增response_format携带的输出Schema没有纳入原8文本的前两项，真实结果证实此请求有额外输入开销。不能把10432直接写成通用固定余量，不能用字符估算Token或跳过真实usage校验。

## 最终规则与交付

保留8项维度、原输入/输出/总量上限及1024 framing门槛。新资源v33/v34的CountingDefinition增加system_text=system_plus_output_schema_v1，精确定义第1项为实际system文本、一个换行、实际SDK response_format.json_schema.schema的compact JSON；其余7项保持。只有SDK有该Schema时附加，不把它作为额外Chat message发出。旧资源字段不存在时仍计原system，旧审计字节保持。

计数文本从冻结Canonical.resources的counting描述及既有纯派生SDK格式取值，校验资源摘要，未知策略失败关闭；不重读当前库、扩充私有材料或放宽预算。八文本摘要、审计恢复、预检/实际usage都继续用同一冻结文本定义，第一项记录系统规则及输出格式合计，不能再称仅system消息的Token数。Wire/layout/GuideRun身份不改，计数资源版本及release摘要标识策略变化，不需DDL或固定构建源变更。

交付包含原子源码修改、新冻结资源、旧请求原样还原与八文本/实际SDK请求绑定专项、两组新输入完整冻结复核、映射及断点。真实新策略计数与供应方开销仍需另行单次兼容观察；若新文本计数与实际usage仍超出原门槛，继续停止，不调大余量或自动重试。先前单例许可不续用。

## 实施结果

v33/v34及计数策略已发布，完整组98项/16子项通过389.18秒，前36项/3子项为重叠专项；两组新v4各60/120生成及全量重建一致，旧121条真实请求按原计数资源还原一致。实际SDK请求不变，Counter首项用完整八文本摘要绑定，不再误与原system消息摘要相等。新策略真实兼容尚未验证，本次单例额度已用完，不能再发请求；详见[验证](../../../verification/v2.1/ai-schema-counting-fix-2026-11-18.md)。正式AI未启用，不合并原设计。
