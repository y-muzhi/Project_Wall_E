# Guard私有文件所有者及未知关闭修复（V2.0）

2026-11-15，pending。依据后端0.17-draft-17第7.3的私有记录、原所有者及未知恢复边界；正式设计不自动合并。本轮用户“继续推进”接续工作区修复／隔离离线检查，系统检查仍按此前明确暂停处理，不安装、重启或改已有资源。

已证实源码缺口：新文件使用默认安全描述符，却用TokenUser（current_operator_sid）校验Owner；Windows默认Owner来自TokenOwner，二者没有必然相等关系。参考[Microsoft Owner of a New Object](https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object)、[File security](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)。此为实现依赖缺口，尚不能确定是2345实际SYSTEM失败的具体原因。

输入为活动PrivatePackageGuard、固定文件角色及有界字节。新文件在CREATE_NEW时显式指定当前operator Owner和原角色DACL，不启用特权，不修已有文件；控制Git读角色仍仅保持原读执行。复用PrivateRecordAppend的原句柄写入、flush、校验及无替换发布，journal锁、launch／action临时记录也走同一路径；仅后续原CAS及原子replace允许替换原状态，不新增任意文件写入API。成功、明确失败、未知发布及清理边界保留。

另修复LaunchJournal.close的确定问题：当前清空_stack后执行关闭，异常时还清除原owner，可能丢失未知资源并允许对象再次打开。改为关闭成功才清空；失败保持原组件／异常及retained_owner，锁住重复close／再次enter。取消或失败清理不重复原生动作。

检查覆盖真实新NTFS私有文件的Owner／受保护DACL／原读角色、已有目标不替换、journal与action更新／临时清理、配置副本、未知关闭时原资源仍持有且不重试、普通冻结journal自检。私有目录均为本轮TemporaryDirectory，结束清理；不查询或改已有SYSTEM journal。不将离线成功写为SYSTEM根因已验证。


关联资源：windows_private_package.py属于Schema200来源清单。更新该模块后必须按现有schema-v20-release流程新增不可变来源发布并原子更新代码pin，保留旧发布；对比objects／fresh／upgrade三个结构资源不变，不操作用户数据库。通信专项的故障注入必须只阻止controller-seal再次发布，不得把正常的journal状态临时发布一并拦截。共享发布错误保持原LaunchOutcomeUnknown／GuardActionError契约，并携带原retained_owner。配置副本的creation_unknown仅在实际CreateFileW前设置，描述符准备失败属于已知未派发。


## 实际完成状态

源码修复及原错误／owner传递、配置副本已知未派发边界完成。核心15文件405 passed／6子检查及5项普通实际管道代表路径通过；新r50三个结构资源与r49逐字节一致。新1525 Guard普通冻结prepare／关闭／重开自检、全包自验及1530输入准备通过。完整证据、早期失败和未覆盖见[验证](../../../verification/v2.0/guard-private-file-owner-2026-11-15.md)。状态：已实现／离线及普通路径已验证，SYSTEM场景未验证；未部署、未合入设计，原系统检查暂停继续生效。
