# D-011基础计数单元（2026-10-06）

用户已确认“确认该补充方案，按稿实施”，见D-011及 [确认记录](../proposals/context-budget-approval-v1.json)。原提案字节保留，未授权真实付费调用。

最终 [counting-adapters-2026-10-06T12-25-45-696Z.json](counting-adapters-2026-10-06T12-25-45-696Z.json)：35项、262输入前后不变，包括新Schema与计数适配测试、既有模型配置/私有审计/C03回归。不是完整后端重跑；此前733完整回归作为历史证据保留。

schema_transport.py 对v1/v2全部六任务保留根关键字与可达本地定义，原签名校验器不变，记录原/派生SHA；拒绝循环、外部/动态引用及未知解析机制。properties等映射的实例字段名不当作Schema关键字。测试同时检查值等价、约束拒绝和资源字节，有限样本不代替引用图前提。[JSON Schema官方标识和引用规则](https://json-schema.org/understanding-json-schema/structuring)说明该解析边界。

tokenization.py 一次固定模型/固定端点POST，真实本机TCP验证确切Unicode批次、响应版本/顺序/精确整数/数组结构、容量、错误/重定向不重试、凭据清除、取消真正关闭连接。官方响应字段来自 [Ark Tokenization文档](https://docs.volcengine.com/docs/ark/tokenization-api?lang=zh)。测试返回计数是明确隔离响应，不是模型准确率或Chat封装兼容证明。无实际Ark或Chat调用。

保留首次 [失败记录](counting-adapters-2026-10-06T12-24-26-148Z.json)：扫描器把实例字段id误当旧Schema解析机制，改为映射值扫描；测试中Python True==1造成预期混淆，改用显式真假预期并保留布尔拒绝检查。原始stdout/stderr不改写。

本单元未接入生产Builder/Audit/ORCH。下一步冻结计数候选、按确切字段计数/整历史和非必要邻块裁剪、审计身份与事务后重查、兼容证明门禁。生产仍保守拒绝；准确文本计数不能代替两角色Chat封装证明，256预留仍须证明。真实模型兼容、效果样本/阈值及付费预算仍开放。
