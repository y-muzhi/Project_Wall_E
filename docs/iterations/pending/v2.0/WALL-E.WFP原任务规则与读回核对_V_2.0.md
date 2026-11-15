# V2.0 WFP 原任务规则与读回核对

2026-11-08，依据 BE 7.3.2。受信 Guard 从已经记录的原 TASK PREPARE 取操作、代次、随机分配引用和配置名称，独立派生 LPAC 包 SID。任务的私有模型入口、转发入口、原生控制和应用端口由 Guard 按同一原输入核对。只接受 127.0.0.1／::1 和有效端口，按原作用域生成稳定规则 GUID。相同输入读回原规则，输入变化不产生另一套有效规则。

IPv4／IPv6 的连接、监听、接收各有一条持久默认拒绝，按任务包 SID 匹配。精确允许在同一已登记子层内排在默认拒绝之前。连接仅允许模型入口及受管转发入口，监听限原生控制／受批应用绑定，接收额外限制同族回环来源和 TCP。监听层无协议条件，协议在连接／接收核对。允许规则不清除后续阻断权。实际 Windows 跨子层仲裁和 loopback 仍须实测。 [Microsoft 过滤层及条件](https://learn.microsoft.com/en-us/windows/win32/fwp/filtering-conditions-available-at-each-filtering-layer) [Microsoft 仲裁](https://learn.microsoft.com/en-us/windows/win32/fwp/filter-arbitration)

Guard 在既有 PREPARE 原记录之后、任何系统网络分配之前，以只写一次的私有 NTFS 文件封存精确网络输入和部署指定的 provider／sublayer。文件与 PREPARE 的原输入摘要、原分配及 owner_epoch 对应。重复只核对原字节，已有确认的 PREPARE 不补造此前缺失的网络清单。重启后的只读核对可使用经 Guard 核实的旧作用域和代次，从原私有 PREPARE 和封存记录重建规则，不重放原准备。该读取方法不授予跨控制方权限或执行权限。

本批实现在一个只读事务逐键核对原过滤器。核对原规则、已登记 provider／sublayer、条件、权重和持久性，任何不符均保留启动阻断。允许清单、规则正向系统证据、对额外规则的覆盖核对、实际仲裁与连接和关闭后释放属于实际派发的独立前置条件。本批不改当前机器防火墙。

## 事务写入与提交未知

原 TASK PREPARE 和已封存清单都吻合、原控制方仍开放、未有 STOP，且 Guard 以未模拟的 LocalSystem 身份运行时，才允许保存原网络安装派发事实。派发事实以只写一次私有 NTFS 文件绑定原计划字节摘要。相同派发记录再次进入时只读原规则。派发记录缺失且没有已接收的当前原准备，不执行写入。

Guard 使用持久会话的单个 WFP 写事务，核对固定 ALE 层及登记的持久 provider／sublayer 关联，按封存顺序增加规则。Filter 使用程序固定的 SYSTEM 对象访问边界。单条失败、取消或核对失败时中止事务。Commit 返回失败或回复丢失时保持未知，只核对原 GUID，禁止重装或猜测回滚。Commit 确认后仍从独立只读事务核对所有原规则。规则已核对只是内部资源事实，实际有效规则覆盖、仲裁与网络测试仍是后续启动前置。 [Microsoft 过滤器添加](https://learn.microsoft.com/en-us/windows/win32/api/fwpmu/nf-fwpmu-fwpmfilteradd0) [Microsoft 事务提交](https://learn.microsoft.com/en-us/windows/win32/api/fwpmu/nf-fwpmu-fwpmtransactioncommit0)

## 同一子层规则集合

在逐键读回的同一个只读事务内枚举全部六个 ALE 层上的登记子层规则。枚举包含禁用及启动时规则，以便识别可能随后生效的条目。原清单缺规则、存在额外同任务规则，或额外规则无法确认仅匹配另一任务的包 SID，均拒绝。读取／释放枚举失败或超出读取上限时不提供完整证据。本规则用于登记子层完整性，Windows 跨子层仲裁仍独立验证。 [Microsoft 过滤器枚举与快照](https://learn.microsoft.com/en-us/windows/win32/api/fwpmu/nf-fwpmu-fwpmfiltercreateenumhandle0)

## 未派发进程的原网络释放

仅在 Guard 已鉴权的原 RELEASE 中处理 TASK PREPARE 的原封存。原绑定、代次、持久停止屏障都必须匹配。必须有原屏障明确显示 CREATE 尚未派发，且不存在 CREATE／RESUME 动作记录。已经派发或可能派发的任务保留其持久拒绝规则，等实际 Job 与退出证据核清后走后续停止单元。

本单元只处理网络资源。仅当原安装曾持久派发，才可按原 GUID 删除。每条存在的规则在同一个写事务内复核归属和全部条件，并核对原子安装只可能留下完整规则组或全部缺失。子层内额外匹配本任务的规则会阻断处理。删除后用新只读事务确认原 GUID 和额外匹配均不存在。提交未知或读回失败时只观察原范围，不再次派发删除。 [Microsoft 过滤器删除](https://learn.microsoft.com/en-us/windows/win32/api/fwpmu/nf-fwpmu-fwpmfilterdeletebykey0) [Microsoft 事务语义](https://learn.microsoft.com/en-us/windows/win32/fwp/object-management)

Guard 全控制方封闭与网络安装派发记录使用同一短门。原 STOP 即使持久化失败，当前 Guard 内存中的关闭意图也阻断后续安装。释放确认只作为网络事实，不作为整个 RELEASE、任务停止或执行准入的回执。
