# 控制Git只读准备包实施细化（2026-11-06）

状态：实施中，技术细化、不自动合入正式设计。来源BE0.17-draft-17的7.3.1—.3及7.7.2／.6：真实Guard不使用服务身份运行CONTROL_GIT，而用原普通后端令牌；配置解析须用受控副本／空hooks等，且不继承个人配置。现PrivatePackageGuard固定current-operator-only，SYSTEM创建的包不能直接被普通后端Git读取，不能用同账户fixture通过冒充真实服务组合。

## 输入、输出及不变量

- 输入：原活动、仅操作员可读写的PrivatePackageGuard父根；程序为原准备意图预先生成并保存的32位小写hex包nonce；实际ControllerPrimaryToken。不是RPC任意路径、SID或ACL文本。
- 输出：父根下唯一control-git-<nonce>新目录，owner仍当前Guard操作员，原owner完整权限；仅原实际普通控制方SID继承读取／遍历／执行所需权限0x001200a9，不含写、删、改ACL或所有者。同SID时仍为原owner权限，此情形不作为跨用户只读证明。
- 创建只用CreateDirectoryW的新对象安全描述符，目标已存在拒绝，不更改旧目录、父目录或其他ACL，不启用权限／提权或解析网络账户。不自行生成新nonce重试未知准备；原名称归原意图供核对。
- 在现PrivatePackageGuard增量支持显式control_git_reader角色，读者只能来自实际原ControllerPrimaryToken已捕获的普通用户，不能传字符串SID自报；原operator-only默认保持。创建额外权限时核对原令牌实际仍适用。
- 原Native源配置锁／字节／身份、PrivateConfigCopy、空hooks、实际原Git命令和Job仍各自核对；只读包不是执行资格。读者身份捕获后，静态ACL核对／原资源清理不要求后端仍存活；新Native创建仍必须重新核对真实控制方令牌及原Scope。不能因已退出重开旧PID或授予新执行。
- Journal和私有回执保持operator-only；不把普通后端加入所有控制／记录包。使用只读准备角色的包不能作为PrivateRecordAppend私有记录目的。不能通过额外ACE、重复／未知／继承权限让原包校验放宽。

## 调用与验证范围

同一角色传到只读空hooks目录：原owner／OWNER_RIGHTS仍仅READ_EXECUTE，另加原读者SID的同样只读ACE，目录必须始终为空且原数据句柄不共享DELETE；不向后端授予创建／写入hook或改DACL。

先修改共享权限算法、创建和成员检查，再接PrivateConfigCopy实际复制／清理；不复制第二套包或配置流程。准备包只服务固定CONTROL_GIT，在生产入口前仍需实际包／用户权限／来源及资源准入。LPAC／模型不能因此访问控制区，不提供普通账户或普通AppContainer降级。

本轮只新临时目录／原普通控制方与自有Job检查，真实SYSTEM服务／跨用户令牌组合仍需后续明确环境证据，不以同SID或合成ACL检查宣称通过。改动若进入Schema SOURCE_NAMES，应发布新编译资源而不升级正常库。既有私有目录、正常用户数据、服务、ACL／WFP策略与真实模型均不操作。
