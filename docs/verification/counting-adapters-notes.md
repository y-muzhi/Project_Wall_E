# D-011基础计数单元（2026-10-06）

用户已确认“确认该补充方案，按稿实施”，见D-011及 [确认记录](../proposals/context-budget-approval-v1.json)。原提案字节保留，未授权真实付费调用。

最终 [counting-adapters-2026-10-06T12-25-45-696Z.json](counting-adapters-2026-10-06T12-25-45-696Z.json)：35项、262输入前后不变，包括新Schema与计数适配测试、既有模型配置/私有审计/C03回归。不是完整后端重跑；此前733完整回归作为历史证据保留。

schema_transport.py 对v1/v2全部六任务保留根关键字与可达本地定义，原签名校验器不变，记录原/派生SHA；拒绝循环、外部/动态引用及未知解析机制。properties等映射的实例字段名不当作Schema关键字。测试同时检查值等价、约束拒绝和资源字节，有限样本不代替引用图前提。[JSON Schema官方标识和引用规则](https://json-schema.org/understanding-json-schema/structuring)说明该解析边界。

tokenization.py 一次固定模型/固定端点POST，真实本机TCP验证确切Unicode批次、响应版本/顺序/精确整数/数组结构、容量、错误/重定向不重试、凭据清除、取消真正关闭连接。官方响应字段来自 [Ark Tokenization文档](https://docs.volcengine.com/docs/ark/tokenization-api?lang=zh)。测试返回计数是明确隔离响应，不是模型准确率或Chat封装兼容证明。无实际Ark或Chat调用。

保留首次 [失败记录](counting-adapters-2026-10-06T12-24-26-148Z.json)：扫描器把实例字段id误当旧Schema解析机制，改为映射值扫描；测试中Python True==1造成预期混淆，改用显式真假预期并保留布尔拒绝检查。原始stdout/stderr不改写。

本单元未接入生产Builder/Audit/ORCH。下一步冻结计数候选、按确切字段计数/整历史和非必要邻块裁剪、审计身份与事务后重查、兼容证明门禁。生产仍保守拒绝；准确文本计数不能代替两角色Chat封装证明，256预留仍须证明。真实模型兼容、效果样本/阈值及付费预算仍开放。


继续完成独立精确组装候选：backend/resources/counting/v1/strategy.json 为固定候选（SHA fbfc01bf6411111f3012e5362218ca1ae76ce6676be5089370f3a3607980b908），状态pending_real_chat_framing_proof且production_enabled=false。独立于原v1/v2协议和预算，读取时必须命中字节SHA，任何预算覆盖拒绝。采用记录为context-counting-adoption-v1.json，冻结Git检查已增加该候选/原提案/采用记录。

[counting-adapters-2026-10-06T12-38-39-687Z.json](counting-adapters-2026-10-06T12-38-39-687Z.json) 46专项通过（新增11项）：actual C03、v1/v2实际Run、精确六段序列化、4096字段与24576+8192总量边界、整条最老历史再正文顺序非必要邻块、每轮重新计数及对应Read Manifest，保留原卡和正式响应来源。真实计数adapter TCP到候选组装通过；受控计数不是实际模型token准确性。实际写事务在计数await边界可完成，编译不持有SQL事务。错误/取消无重试，审计容量超限不丢证据后继续。本次暂无新的失败。随后仅删除未使用导入并完善验证范围文字；完整后端回归另记录。

候选组装本身完整，无生产调用方；仍未接入AuditRepository/可信结果原请求校验和ORCH异步流程。成功结果始终compatibility_proved=false；256封装预留没有被当作真实证明。不把独立组装通过当作生产AI可发送。下个单元按真实C03再查计数请求/派生Schema/Read Manifest、私有审计版本与取消/退休接线；付费兼容执行器及真实样本门禁待完整准备后再按既有约束审查。


最终源码完整后端回归：[P2-2026-10-06T12-51-05-665Z.json](P2-2026-10-06T12-51-05-665Z.json)，758项/545.219秒通过，263输入稳定、依赖及来源检查通过。覆盖删除未使用导入后的最终候选；此前46专项保留原始输入hash，不覆写。758包含这些专项，不能相加。未把通过测试解释为真实Provider兼容或所有正式场景完成。
