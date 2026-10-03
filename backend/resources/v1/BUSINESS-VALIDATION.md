# Schema之外必需的业务校验（待确认）

这些检查必须由程序实施，不因JSON Schema通过而省略。

- 读取对象/版本/消息来源真实且同需求；Read Manifest与实际读取一致；ASK/REVIEW allowed_targets=[]；INITIALIZE/各MODIFY按服务端解析冻结授权。
- min<=max、可选数量不超过options加可用自定义；卡片/选项键按字段唯一，推荐必须引用现有选项且不能产生选择；related_spec_context来自实际读取。
- 正式responses恰好覆盖原卡片全部，必答不跳过；非必答未答显式跳过；single/custom互斥，multi计数包括非空custom；skipped答案为[]/null。
- BlockState结构/元数据/日期/来源、Markdown顶层方言顺序完整一致；已有创建来源不变；next高水位不回退；范围半开区间start<end且码点位置对应。
- 原文逐字比较、Patch授权和组合一次性验证；表格键唯一且列数一致；SELECTION证明选区外不变；初始化锁定标题不改，confirmed_fact_patches证据只能来自真实USER或正式CARD_RESPONSE逐字可见文本，模型自报证据仍需回查与事实一致校验。
- REVIEW证据必须在当前读取原文，issue_key唯一，source历史结果确来自同需求已完成REVIEW；来源comment未删除OPEN且真实定位，不能扩大授权或自动解决。
- 任务分支与本轮状态复查；取消/终态/版本变化拒绝迟到业务写；输出只能在全部校验后trusted。
- 模型不得输出持久Suggestion ID/order/status、人工决定、时间和作者来源；由程序分配和赋值。
- 消息可读content与卡片/正式答案等价，未知用量null，非法结构不伪装成功；以上字段容量为候选，待Q-10确认。
