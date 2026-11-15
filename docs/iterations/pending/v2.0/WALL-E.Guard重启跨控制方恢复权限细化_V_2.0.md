# Guard重启跨控制方恢复权限缺口（2026-11-06）

状态：用户已确认建议窄恢复权限，待实施；正式设计不自动合并。来源：BE0.17-draft-17第7.3.1—.3要求真实控制方进程／owner_epoch绑定、幂等域含控制方；第7.3.3／7.7.7又要求重启沿原scope核对。正文和Windows受管执行迭代未明确新控制方可以访问旧控制方哪些资源。当前接收实际peer与原Native身份核对后，后端重启的PID／创建时刻及ProcessLock.owner_epoch均已改变，不能把旧scope当新控制方继续执行，也不能靠原nonce自报身份。

## 建议：同安装／用户／已准入后端程序的窄恢复

1. 新请求仍以新实际本机peer／原程序包／当前owner_epoch认证，不能冒充旧PID或旧原令牌。原控制方身份只作旧记录定位，不作为新调用者权限。
2. 只允许OBSERVE、STOP、RELEASE定向旧原scope；禁止借旧身份PREPARE、CREATE_SUSPENDED、RESUME、VERIFY_MODEL_SOURCE，不换nonce、原输入或资源。旧工作未核清前不创建替代实例／任务。
3. 必须核对同一安装、同一真实用户、同一已准入后端程序／包以及Guard原持久控制方记录与原operation／step／nonce；旧控制方已退出或其接收域由Guard可靠封闭。不能仅凭请求body、SID、PID、nonce、文件路径或新后端声称失去锁放行；不跨仍活动的其他控制方。
4. 原backend捕获的新身份不改写旧Controller／OperationStep／GitReceipt。内存仍有原句柄时只核对／停止原对象；Guard重启后丢失原Job／句柄时不凭名字或PID重建。查无记录、程序来源缺失、封闭或归属不明仍UNKNOWN，不自动宣布未执行、已停止或清理完成。
5. 当前调用头为新调用者绑定，input中的recovery={controller_ref:旧原引用,owner_epoch:旧原epoch}仅用于上述三动作；operation_id／step_no／nonce仍原值。OBSERVE另保留observed_action，旧binding_ref若已知仍须与原scope相符。这不是新业务根、第二命令账或任意资源接管。
6. 后端不因此读Guard私有文件或提升；Guard仍不读业务SQLite。必要原控制方登记随既有私有Guard归属载体在第一次外部动作前持久保存；缺原证明不自动补签旧记录。服务安装、既有ACL／WFP改变、付费调用与正常数据操作不在本轮授权。

## 备选：拒绝跨控制方恢复

维持实际身份精确匹配；后台重启后的旧scope保持待核对，需专门人工维护才能收口。实施较简单，但与产品期望的自动原操作核对链路不能完全闭合。

## 待确认范围与并行工作

本问题是正式设计未明确的旧资源访问授权边界，需要用户选择；不把它解释为每个模块都要批准。确认前继续当前控制方绑定、严格公共头／动作输入校验及其他不依赖跨控制方权限的工作；旧scope跨控制方路径不实施。

## 用户最终确认（2026-11-06）

用户已明确“按建议实施窄恢复权限”。以上建议全部作为本轮授权边界：同安装／真实用户／已准入后端程序、旧控制方退出或可靠封闭、仅原OBSERVE／STOP／RELEASE，禁止旧身份创建／恢复及缺证据放行。此结论替代前文待确认措辞；不需要再次询问，不自动合并正式设计，不扩展系统安装／既有ACL／网络／正常数据或模型调用权限。先完成当前只读准备包完整单元，再接原记录和窄恢复。

## 实施接入顺序与当前边界（2026-11-06）

先保持当前公共头真实peer／epoch，把recovery严格解析为旧scope选择器，仅三动作且不带替换输入；该解析不授予权限。GuardControllerRecords复用原operator-only LaunchJournal及PrivateRecordAppend，在首次launch前从实际CLIENT peer保存原Native身份、图像原FileID／字节和受信安装目录引用；不读业务库，不新建命令账。缺登记的既有launch／native记录禁止补签，重启读取不重开PID。程序／包引用是Guard受信安装输入，不是RPC字段，也不能单凭记录认定程序已准入。

后续实际放行仍须保护后端程序／完整包准入、当前peer复核、同安装／用户／程序和旧控制方退出或可靠封闭证据；当前记录和解析单元不派发Native或宣告停止／清理成功。普通Python解释器图像不是完整后端程序证明；安装／打包准入完成前拒绝激活该权限。

## 可靠封闭分支实施不变量（2026-11-06）

封闭不是停止或清理完成。Guard在原operator-only归属目录以原控制方登记SHA／epoch保存不可覆盖的controller-seal；原Journal的PREPARE及CREATE／RESUME派发意图在短全局门内复核该封闭，Native回调不持全局门。封闭先阻断整个controller_ref（包括新nonce和另一个Registry），再逐原scope等待在途派发归还并持久close_nonce；不能只设置某个Registry内存标记。发布未知保留原writer／FileID，当前Guard同时保留易失拒绝标记，未核实不回复可靠封闭。

恢复遇到旧进程仍活或观察未知时，须取原登记匹配的持久seal并核对原target fence已封闭；缺任一仍UNKNOWN。Guard重启失去原Registry／Job／句柄不因有seal自动声明已停或已释放；这仍只提供窄恢复权限，不重建旧对象、不创建／恢复进程。binding_ref固定为PREPARE原资源绑定（CONTROL_GIT当前为原entry.job_ref），不是后来根进程resource_ref或任意Job名。

## 仓库执行队列接续

正常后端新 ProcessLock 先按原操作 ID 核对启动时已处于 RUNNING 或 UNKNOWN 的登记与观察。核对原回执、固定步骤及私有回执目录，按原步骤中已保存的 nonce 列表读取原派发事实。未保留范围或范围无原 PREPARE 意图时无需向 Guard 发送动作；原 RELEASE 已核实则复用原证据。已可能派发且未确认释放的范围，在当前连接携带旧选择器查询原 PREPARE，按原 STOP／RELEASE 意图决定查询原动作或首次请求清理。已有意图的动作只能查询。Guard 负责当前准入及旧退出／封闭授权，找不到原持有者时维持 UNKNOWN，队列等待原范围可核实后取新工作。

启动核对不会收集已经丢失的 stdout、恢复旧进程或改写原 202。原保存已提交则继续读取原成功结果；仍执行中的原读取按原步骤记为 UNKNOWN。确认资源释放可结束本轮清理，业务结果仍为 UNKNOWN。继续使用现有原动作回执，无额外账本或库迁移。

Guard 新控制方登记的禁止补签屏障以当前真实 controller_ref 为范围。同一控制方只要存在尚在生成或既有的启动／原生记录，就不能补签。旧控制方的停止监视可与新登记并行，其记录仍按原身份核对；原恢复门仍独立要求旧进程退出或可靠封闭及目标作用域没有在途写入。
