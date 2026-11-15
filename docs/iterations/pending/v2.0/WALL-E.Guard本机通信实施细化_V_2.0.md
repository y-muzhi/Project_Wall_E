# Guard本机通信实施细化（2026-11-06）

状态：实施中；细化既有BE0.17-draft-17的7.3.1—.3／7.7.6技术调用，不自动合入正式设计。固定WIN20-ISOLATION-1及原七类动作、控制方／owner_epoch／原operation／step／nonce、未知只核原作用域等规则保持。

## 原端点与身份

本机固定命名空间\\.\pipe\WALLE.RuntimeGuard.<已登记64位小写hex安装引用>；新服务端只创建首次实例、单实例、字节双工及OVERLAPPED，显式PIPE_REJECT_REMOTE_CLIENTS，原句柄不继承。新对象DACL只含原服务端SID完整权限及已登记后端SID的数据／读取属性／READ_CONTROL／同步权；不同SID的后端ACE不含FILE_CREATE_PIPE_INSTANCE。相同SID合并为原owner权限仅属同账户组件检查，不因此准入普通账户替代Guard服务。

客户端只打开此原本机名称，不等待后自动换实例或创建服务；使用显式最小权限及Identification SQOS，不授予Impersonation／Delegation。核对原精确DACL及服务端SID，绑定可信登记的Guard进程完整身份和ExecutablePin原程序对象。服务端还须在处理协议动作前核对真实后端peer／程序及owner_epoch。PID、SID、路径、hash、nonce或JSON自报均不是完整认证。保护运行包、安装清单、双向协议及LPAC-WFP准入未完成时保持不可执行。

## 有界IO与帧

端点、peer及IO／帧由创建线程串行拥有；它们的长期程序／端点租约不能跨线程退出。跨线程调用在碰锁或OS句柄前明确拒绝；其他线程通过原取消信号通知所属通信循环，再由原线程核对／关闭，不在任意线程池重建或转移身份。

每个原IO只用自己的OVERLAPPED／手动事件、缓冲区和原端点，最多65536字节；读写／连接使用调用方明确时限及取消观察，禁止INFINITE和PIPE_NOWAIT轮询替代重叠IO。时限／取消后只CancelIoEx原IO，再最多1000ms确认原完成。无法证明完成时进程内强持有原分配及端点，显式保留原owner，原连接不可复用；关闭或后续核对仍用同一OVERLAPPED，不能把取消返回当完成。

下一内部帧采用4字节无符号大端正文长度＋UTF8 JSON对象，正文1—65532字节，整帧≤65536；不写消息分隔符、不拼多份JSON、不自动修复编码或重复键。根为对象，拒绝非有限数、非法Unicode／非文本键及超安全范围整数；深度最多32、节点最多32768（含键）。发送按固定排序确定序列化。读取头与正文共用一个原调用期限，坏长度／半帧／非法JSON使原连接失效，不当空响应或重新同步后重发。JSON结构解析不授权任何动作；七类动作及原owner／scope的严格decoder／调度仍须单独接入，不把任意input JSON直接交Native callback。

## 验证与边界

已有原peer、端点、客户端及有界IO检查记录在verification/v2.0；帧与原协议绑定继续逐批实施。只用新临时管道、自有Job及隔离数据；本轮不安装系统服务或变更现有ACL／网络，亦不调用模型。组件或普通测试进程通过不作为完整Guard服务／任务隔离／系统安装验收。

## 原控制方绑定与请求头（继续实施）

控制方引用由Guard实际已核对CLIENT peer身份、原owner_epoch和已登记安装引用确定；后端只从当前原ProcessLock及自己的OS身份计算相同引用。确定JSON沿LaunchJournal._bytes的排序及尾换行，SHA256作为controller_ref；不包含新连接随机值或Guard新进程PID，重连仍定位原作用域。引用是身份路由摘要，不是签名或凭证；接收方必须独立核对原peer／程序／保护包，不采用RPC自报NativeProcessIdentity。

原请求公共头固定protocol_version=WIN20-ISOLATION-1、action（原七动作）、controller_ref、owner_epoch、operation_id、step_no、nonce、binding_ref、input；全字段必有，未知字段拒绝。owner_epoch为原小写UUID v4，scope复用LaunchScope原校验；binding_ref只为原不透明资源引用，PREPARE为null，CREATE_SUSPENDED／RESUME／RELEASE／VERIFY_MODEL_SOURCE须有原引用，STOP／OBSERVE允许null以核对原未知／从未创建nonce。OBSERVE的input仅{observed_action}，明确定位除OBSERVE外的原Guard动作，不按最新状态猜测。

公共头解析只冻结原input JSON，不执行动作或核实其业务权限。原七类动作各自输入、资源／实际程序及原步骤匹配、owner_epoch活动准入、Registry和Journal调用仍由实际handler落实；不得将公共头或输入摘要当另一份幂等业务账，未知创建不因此重发。Backend本地绑定检查会确认原ProcessLock仍归本进程及原epoch；Guard不访问业务SQLite或声称能远程证明OS锁持有。

## 连接与原控制方资源寿命（2026-11-06）

生产controller owner须从真实peer已经持有的原进程句柄取得同权、不可继承的DuplicateHandle副本，并自行保留到全部原Job／步骤核清。令牌watch不能继续借一个随旧管道连接释放的peer._process，也不按旧PID重开。原进程副本不增加控制权／终止权，仍核对原PID及创建时刻；断连接后只继续观察同一OS进程对象。Guard actor在同一所属线程执行原TypedCommand／文件／程序租约生命周期，新连接重接沿既有controller／epoch／scope，不跨线程释放长期RLock租约。

控制方watch还需独立于执行令牌长借用所持source._gate：原Native观察副本只读同一内核进程对象，不能让一个在途创建／准备阻塞其他原Job的安全回收。watch自身的原句柄副本在原scope全部封闭／Job空／根退出、监视线程停止后关闭；关闭失败保留原owner。Native callback不持全局元数据门，不因source门占用而换PID或盲杀其他对象。
