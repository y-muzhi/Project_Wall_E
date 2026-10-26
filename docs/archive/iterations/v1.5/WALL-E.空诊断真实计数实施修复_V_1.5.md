# 空诊断真实计数实施修复

2026-10-23，已合入正式BE AI-RESOURCE第7部分，见同日合并记录。本次经用户明确授权的有限真实观测，实际Tokenization八项成功，三个空字符串各返回1；程序误加空文本必为0的约束，导致Chat前CONFIG_INVALID。不是供应方计数失败。

最终规则：所有8项保持原收据的实际非负安全整数；只检查system／user完整输入计数为正，预算及framing仍只用system＋完整user，不把诊断再次相加。空分区语义“未携带”和空文本Tokenization实际边界token分开；不归零收据、不伪造usage，不放宽模型／请求／摘要／向量维度／token数组复核。

实现仅collaboration_counting.compile_counted／verify_counted移除误拒绝，新专项覆盖空诊断正计数的接受、原值保留及固定预算。计数／观测／准入联合18 passed／86.37秒；原始真实计数在原文本逐字节校验下离线重放通过。无新真实调用；前次许可已结束，正常数据库及计数审计保留，release仍OFFLINE_READY，无Chat证据不可LIVE_VERIFIED。

Wire、Prompt、Schema、计数文本、profile、framing、硬预算均未变，v9／v10冻结资源字节不变；不为程序错误修改原观察结果或原资源摘要。精确结果见live-admission-once-2026-10-23.md；后续真实观测需要新的明确许可。
