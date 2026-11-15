# Coding未来检查输出上限的显式应用 V1

2026-11-11香港22:15，BE 0.17-draft-17／FE 0.16-draft-16，沿本日检查标准迭代及正式APP-CODE-CONDITIONS、ExecutionLimits、7.6.3／7.6.6。独立pending，先于本单元代码保存，不合入正式设计。

## 输入、输出与不变量

仅把 max_check_output_bytes 纳入原C39允许变更字段，其他六类调用／等待限制与新CheckSet支持保持；捕获规则及内容容量仍固定，max_check_cases／max_case_steps／max_case_payload_bytes尚未接入Coding受控案例，不放开无实际执行的字段。活动检查／模型／未知操作等未结案时仍拒绝，不在原检查中修改上限。

复用原TaskConfigurationApplication、授权绑定、四步骤及原同组只读观察。提议与采用均读取实际角色链、固定检查集合、命令／资源及部署准入；检查输出限制发生变化时，接收步骤同时固定 min(profile.max_check_output_bytes, authorization.max_check_output_bytes)，采用前以原配置／授权重新核对。旧CheckSet-only保留事实无需新增字段；历史读取严格核对本次具有的字段与原不可变profile／授权，不能依赖当前目录。

未来实际项目检查沿TaskProjectCheckWorker读取新组的较小值，冻结在原CodingProjectCheckClaim.max_output_bytes、原派发及结果验证中；恢复仍用原claim，不采用后来的配置。超限的检查Item为FAILED／OUTPUT_LIMIT，原输出不作为完整证据，预览按UNAVAILABLE显示，不能截断后算PASSED。配置应用自身不触发检查、模型或计数。

## 交付和完成条件

1. 纯配置上限变化与仅授权收紧均可明确应用；不适用检查／资源／准入在绑定前拒绝。
2. 前端显示目标有效输出上限及原授权范围，UNKNOWN不显示生效。
3. SQLite／HTTP、原操作未知恢复、STOP、冻结上限及原资源撤回；实际Guard新标准／原三阶段链复核较小值进入真实项目检查。原生消息与供应方证据分开。
4. 独立待测试／待接收的原报告、Plan及交付互斥继续按上个pending核对，不用本单元掩盖未覆盖。

本限定单元已实现，SQLite／HTTP／实际Guard的1字节拒绝与64字节恢复、实际Chrome及固定内容禁用均已验证，详见[本轮验证](../../../verification/v2.0/coding-check-configuration-2026-11-11.md)；正式设计未合并，真实供应方及待接收合格报告／Plan联合不计完成。用户本轮两小时授权边界不变：仅隔离离线、Windows／NTFS／Guard／HTTP／Chrome、类型／格式／构建，无真实供应方、正常库、服务更新、SYSTEM／WFP、Git提交推送。源码原子替换与自有产物清理规则保持。

## 固定内容版本的错误说明（22:20，先于本补充代码）

完整复核正式7.2.1—7.2.6后，capture_rules及相关文件／快照／枚举／清单／捕获时间／Git读取容量属于固定内容版本。保持实际拒绝能力，并把合法但不适用当前Task的变更明确归为PRECONDITION_FAILED，接收前不绑定新授权、不建应用、不改候选。已开始及未开始但已固定基线的Task均不能借C39改内容规则；选择新任务／起点与内容配置处理。

前端对同一内容字段显示“此版本更改了固定内容规则或容量，须使用新任务”，提交按钮禁用。服务就绪与所选配置不适用分开；此项是现有设计边界的准确接入，不新增内容迁移或热换能力。按HTTP／SQLite和真实页面选中状态验证，正式设计仍不自动修改。

## 真实输出超限及恢复专项补充（22:25）

沿同一实际Guard任务，初次新检查冻结授权64字节（profile128）；随后明确应用1字节并对原候选重新检查，真实输出超限须是PROCESS_EXIT Item FAILED／OUTPUT_LIMIT且eligible=false，原候选不变。再次明确新授权64字节后重检成功，再接两次角色、修复及发布恢复。原输出超限不能转成未知后自动重跑；每次检查都是独立明确VERIFY_CANDIDATE。该扩展已实际执行，原输出超限未被算作通过，恢复上限后明确重查成功；具体本轮命令／结果以验证记录为准，不挪用早期Guard结果。
