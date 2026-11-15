# 原生权限原会话来源绑定迭代 V1（V2.0）

2026-11-13；实施前登记，保留pending，不合并正式设计。依据BE APP-CODE-CONDITIONS、7.4.3—7.4.4及现有原生权限原意图／回执规则。

## 输入、输出及不变量

现有底层apply_permission以调用方expected加实际GET相符作为PATCH前提，尚缺原创建记录及正回执绑定。本批仅补此依赖，不开放完整C39：原启动范围中的创建意图／严格正ACK必须确定唯一session；before的id、title、agent、model、metadata与permission全部匹配原创建事实，不能由当前GET和调用方同时提供的值自证。权限PATCH仍要求原APPLY_PAIR第3步及deny-all显式重置；一次原意图只允许原发布者发送，未知只读恢复。

恢复前重新读取原创建记录及回执，before与原来源不符、损坏或缺失均在HTTP前拒绝，不补错误ACK。首次应用后最终原生规则仍为有序before+rules；不把PATCH返回当证据。首次前驱来自原创建；继任会话及重复原生更新按下节的完整来源／前缀核对。业务已采用链的生产者接入仍是后续，不能通过放宽比较支持。

本批不新增API／Schema／资源，不改变CONTROL_ONLY，也不授予权限编译／OS同组或新模型调用能力。使用现有真实loopback／私有NTFS专项及必要调用方回归，不读写用户库、凭据或重启服务。

## 接续：继任会话来源

原HANDOFF／REPAIR已经使用SuccessorSessionScope，不应把所有权限更新固定回原START会话。底层apply_permission可接受程序提供的原创建LaunchScope（同controller、原创建第1或4步；不得指本次APPLY_PAIR），并将该完整scope写入原权限意图。原创建ACK及metadata必须与原实例的task_id／instance_id一致。恢复从原权限意图重建来源，只读核对；不能靠当前HTTP提供新来源。旧无来源字段的原意图只按原START创建解析。此参数不接收HTTP输入、不代替业务当前会话和授权验证；完整C39生产者仍待接入。连续原生权限前驱链按下节核对，不自动挑选“最新ACK”；业务已采用来源接入仍待后续。

## 接续：重复更新的原生前驱链

权限更新不应永远只接受创建时permission。继续补底层显式前驱列表：调用方只能给出同controller、原APPLY_PAIR第3步的LaunchScope，程序保存完整列表并逐个读取原意图及严格正ACK；每个before须等于前一确认结果，来源须同一创建scope，各自列表须恰为先前前缀，禁止环、重复、跳项、乱序、他会话、未确认或损坏记录。当前GET不建立前驱资格，不自动选择最新文件。最终before须精确等于完整有序累积permission。

前驱ACK只证明原生读回，不证明业务已采用。未来C39调用方必须只传已采用且与当前业务实例／会话绑定的原操作列表；本批不会把原生ACK自动写成APPLIED／EFFECTIVE或改变HTTP授权。原生库支持重复更新不等于完整产品能力接通。

## 实施结果

上述三项底层单元及停止栅栏已实现；最终四组267项通过，详见[验证记录](../../../verification/v2.0/native-permission-origin-2026-11-13.md)。没有提升完整C39／OS／供应方状态，保留pending。
