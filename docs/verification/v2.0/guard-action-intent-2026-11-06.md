# Guard原技术动作意图与预留引用（2026-11-06）

按[先保存的细化](../../iterations/pending/v2.0/WALL-E.Guard原技术动作与资源准备实施细化_V_2.0.md)实现，V2未提交；BE／FE未合并，db20-r15／code20-r2不变，无正常库升级或服务变更。

guard_action_records.py／guard_action_journal.py复用原LaunchJournal私有根、原scope门及全局元数据短门，保存五个副作用动作的原MAY／ACK记录。PREPARE首次持久MAY时预留binding_ref和directory_nonce，随后才能由原调用方分配；重复MAY返回first_accepted=false，不重新分配。摘要沿原target_scope／owner_epoch／动作语义，排除新的caller认证信息／recovery选择器；原首次caller审计字段不改写。输入差异拒绝；原准备／创建ACK和Native派发／停止fence相互核对，缺旧意图不补签。

结果有界确定JSON快照、返回独立副本；原ACK仅同结果重读。元数据原子保存、flush及fsync、原字节并发复核、替换后核对；丢失BEGIN回执只读原MAY，失败ACK保存保留原完整记录并清理本轮stage。NO_RECORD不是未执行证明。本组件不派发Native或授予权限；实际handler仍须严格动作decoder／当前程序owner或窄恢复门。OBSERVE定位原动作事实，VERIFY_MODEL_SOURCE实时只读来源检查，不把查询缓存当Native副作用结果。

## 实际检查

标准受限环境的原Journal IO端口22通过2.78秒；增加新caller不改原effect与首次审计后，结合owner／恢复端口及自身只读句柄64通过、1条既有Starlette弃用警告，2.93秒。Callback全部明确端口，不当真实原生执行／完整准备。

普通非提升隔离检查首次审批超时未执行，按工具允许正常重试后7文件159通过、1同类警告，14.59秒：test_v20_guard_action_journal.py、test_v20_runtime_launch_journal.py、test_v20_guard_controller_records.py、test_v20_guard_controller_owner_native.py、test_v20_guard_controller_binding.py、test_v20_guard_recovery.py、test_v20_guard_controller_owner.py。

其中新增实际私有根用例从真实CLIENT绑定保存原MAY，再用实际ControllerPrimaryToken和预留nonce创建新读取子包，重复不换引用；只完成部分目录，保留MAY，没有伪造PREPARE ACK或Native Job／进程。SYSTEM／跨用户与真实程序准入仍未验证。226个app文件Ruff格式、两模块lint、git diff --check通过；清理dry-run JSON=0／screenshots=0，无活动检查或当前审批阻塞。

## 剩余

尚未接生产IPC及动作decoder／资源工厂；准备中的部分资源须进入原watch／停止范围，完整RELEASE尚未实现。不能把技术记录当完整PREPARE流程；ready／runtime_admitted=false，实际HTTP仍19条，无新页面或真实模型。
