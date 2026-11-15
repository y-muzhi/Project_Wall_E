# 原生回执关联与恢复前校验 V1

2026-11-12 香港19:24接续约半小时任务。BE 0.17-draft-17／FE 0.16-draft-16及Schema200 db20-r44沿断点不变，仍DRAFT；先保存独立pending，不自动合入正式设计。

## 输入、输出及不变量

依据7.4.3原生未知恢复、7.3.3原nonce／所有者及APP-CODE-CONDITIONS的原步骤约束。TaskNativeActions的原ACK不能只取result中的会话ID。先核对scope／action／完整input与原intent，保留精确JSON类型；再核对session、initial及permission各自完整结果。畸形、别的动作或输入回执在GET／消息POST前拒绝，不创建新意图，不以真实GET反向证明错回执。

无ACK且存在原意图仍沿原方法只读核对，读到精确事实后补原ACK；有合法ACK也继续真实GET核对，不把缓存当生效证据。session ACK只能定位原session；initial ACK须原messageID且accepted严格true；permission ACK须原session及before+rules的精确有序结果。单次副作用及STOP检查保持，不增加重试或全局配置。

## 验证及边界

实际loopback HTTP／NTFS的冲突回执、恢复／丢回执、STOP、跨进程恢复及调用方回归；注入只在隔离私有记录中，不改业务库。只留Markdown，临时资源清理，源码原子保存。不真实模型／计数，不启停用户服务，不SYSTEM／WFP、不提交推送。完整原生规则编译／OS同组／第三步公开状态仍未完成，本批不开放其他scope。


原角色／修复的planned初始消息恢复同样先核对完整信封、scope及native_message_input，再读取parts或返回给调用方固定摘要。缺字段／畸形JSON按原TaskExecutionError拒绝，不让KeyError或非法计划进入后续步骤；合法计划仍同messageID／partID，不重新分配。该校验先于本次源码修正登记。


## 当前实施状态

完整ACK关联、丢ACK的原创建／消息目标验证、固定计划恢复预检已接入实际路径；最终三原生文件143项、相关调用方42项通过。冲突读取注入和真实NTFS错绑回执重开分别覆盖，合法恢复保留原身份，不重发。详见[本轮验证](../../../verification/v2.0/native-acknowledgement-2026-11-12.md)。本文件仍pending，不合入正式设计；通用C39权限编译和OS同组仍未完成。
