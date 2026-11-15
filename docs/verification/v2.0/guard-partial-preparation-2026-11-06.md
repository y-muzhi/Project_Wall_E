# 部分准备资源的原owner及停止（2026-11-06）

按[原动作与准备细化](../../iterations/pending/v2.0/WALL-E.Guard原技术动作与资源准备实施细化_V_2.0.md)实施，不改正常库／服务或正式设计；V2未提交、db20-r15及code20-r2不变。

runtime_control_git_preparation.py：PREPARE原MAY／预留引用先存在，原Registry在任何工厂调用前保存ControlGitPreparation；注册资源角色及精确类型，actor线程分配与关闭。每个返回／失败retained_owner在原令牌存活检查退出前保留，当前控制方退出、原停止或封闭后不再分配，迟到Job仍保留并请求终止。未知构造结果不当无资源、不重试工厂；已知句柄仅在原nonce封闭／无活动后逆序关闭，失败保持确切原owner。此处不删除目录、不代表完整RELEASE。

ControlGitRegistry原watch／STOP／close_watch已包含部分准备列表，观测副本不等待执行source锁。原资源未核清时保留watch；重复同意图返回原owner，重启查无内存owner不重建。部分owner到完整Entry的转移尚未启用，当前register明确拒绝ORIGINAL_PREPARATION_TRANSFER_REQUIRED；没有以占位Entry伪装完整PREPARE。

## 实际检查

标准受限环境部分owner端口＋原意图两文件32通过、1条既有Starlette弃用警告，3.43秒。覆盖停止在前／构造中／构造返回后来源退出、原retained_owner、未知禁止重派发、错类型、逆序关闭及失败重试同对象。

普通非提升隔离8文件124通过、1同类警告，47.87秒：部分owner／原意图、实际owner、Registry、Guard崩溃、原控制方登记、owner／窄恢复。新增实际用例在原令牌存活context中创建真实新匿名Job，终止本轮原backend测试进程后才返回Job；context退出失败，原Job仍由部分owner保留、watch沿原句柄核对退出并调用实际TerminateJobObject，原nonce封闭后关闭原Job。实际PREPARE仍保留MAY，不伪造完成。源程序准入只为明确端口，真实私有记录仍无准入。

首次该轮审批服务403未执行，正常重试恢复后实际取得上述结果，未绕过审批。227个app文件格式、两模块lint通过，尚待收口diff／产物核对。临时目录和自有进程随原上下文清理，无普通用户服务或真实模型调用。

## 下一步

将完整准备资源按原预留binding_ref原子绑定到现有Entry，保留部分owner／辅助资源生命周期；接严格decoder与生产资源工厂和七动作。目录原FileID清理、完整RELEASE及SYSTEM／保护包／LPAC-WFP正向仍未完成，不能把句柄关闭当清理成功；ready=false，无新增HTTP／UI。
