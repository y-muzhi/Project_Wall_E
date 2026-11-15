# Coding原生权限应用与恢复 V1

2026-11-12 香港11:01启动，用户要求约一小时推进。基线BE 0.17-draft-17／FE 0.16-draft-16，SHA及工作区沿当前断点复核，仍DRAFT。本文件先于代码保存；独立pending，不自动合入正式设计。

## 输入、输出及不变量

依据APP-CODE-CONDITIONS 4.3、7.3.2—7.3.5、7.4.2—7.4.4。复用C39原应用／授权和四步骤、TaskNativeActions原私有意图／回执、原实例受鉴权本地HTTP及directory。不得修改全局config、重启实例或新建会话代替配置变更。

先完成原生固定协议、精确有序permission载荷和同原动作的未知恢复；PATCH成功本身不表示APPLIED。规则按固定版本合并，不能用空数组撤销。调用方须提供原会话、完整旧策略、新编译规则及预期最终规则；同实例、agent、model、metadata及目录全部核对。原意图先持久化再外发，丢回复只GET原会话，不重复PATCH；策略漂移或缺证据保持未知。检查点仍负责STOP／代次／所有权。

底层协议不能代替授权编译、实际OS同组边界和C39事务采用。本轮分单元保存，不把尚未生产接入的基础方法当完整配置应用。原创建／消息的恢复不改语义，既有调用方保持兼容；新增外发不能绕过原持久动作。

## 批次及验证

1. 固定提交session handler及permission merge／evaluate源码核对；本机HTTP真实鉴权／目录／一次PATCH、丢回执／只读恢复、规则及身份漂移、STOP／并发意图、字节容量，临时NTFS私有包原记录。
2. 原C39依据／规则编译／OS边界和原步骤持久接入；完整满足条件才开放限定字段。不能安全处理的范围仍明确拒绝，记录具体依赖。
3. 按实际改动执行关联专项和锁定Ruff格式；前端有实际变更才做对应类型／页面检查。仅留Markdown，临时进程和输出清理。

本轮允许相关源码和隔离离线检查，不触发真实模型／计数，不改正常业务库／服务，不安装SYSTEM／WFP，不提交推送。保留其他修改、源码同目录临时fsync／原字节复核／os.replace。

## 原持久动作并发外发保护（复核后、先于实现）

复核共享_begin发现read-then-_write在两个同组调用同时通过首次读取时，后者可能读到相同已写意图并当作自己的写入，产生二次创建／发送。虽然生产入口有单写入者，持久动作本身不应把“相同意图已存在”当新的派发资格。将_begin直接使用原NTFS no-replace发布取得唯一创建权；已有或结果未知一律不外发，沿原身份观察。原_ack仍允许相同事实幂等保存，原记录命名／历史内容不迁移。需要真实NTFS竞争与原创建／消息、继任会话、角色／修复专项，不能仅以线程锁证明跨对象排斥。

## 外发前完整载荷冻结（先于实现）

共享创建／初始消息在控制适配层才校验完整载荷；调用者先保存意图后校验会把确定非法输入留作待恢复动作。将原校验抽为相同纯函数，在持久意图前执行并通过确定JSON快照切断调用者别名，网络发送和核对使用该原快照。保持原生字段及容量，不增加宽松默认。创建、消息、权限分别补非法输入零意图／零HTTP与检查点修改原对象的实际测试。

## 固定记录的容量与恢复校验（11:24，先于实现）

原生载荷容量与带scope／动作／回执包装后的私有记录容量分别核对。保存意图前确保完整原记录可保存；权限动作还须预核旧规则加新规则的最终ACK可保存，不能等PATCH后才发现原回执超限。恢复时按同一严格输入函数重核原before／rules，缺字段／非法规则／缺reset等不得发GET或形成ACK；仍不重PATCH。此项是持久恢复契约完整性，不放开C39授权范围。


## 固定原生循环与后续衔接

已完整核对固定提交session/prompt.ts的原循环及session/tools.ts的工具构造：旧循环进入时读取原session，再把该对象交给工具；agent规则在前、session规则在后。向同一会话PATCH不能被解释为旧循环已重新读取新规则。因此后续C39仍须沿原窗口CLOSED及实际QUIESCE证据，不把本轮底层方法用于尚未核清的活动写入。PromptInput.tools会另行设置session规则，WALL-E原生消息保持严格字段白名单，不增加tools字段旁路。

后续未完成调用点：reserve_live_configuration须在原C39第三步固定目标策略及原nonce；driver从已验证的固定组取得新NativeCodingPolicy，沿原TaskNativeActions观察源保存旧策略；未知仅observe_permission。采用前重读原生config／providers、原session、Guard及受管入口，全部同组才以原事务提交；后续observe_control_configuration及原会话恢复不能继续只比初始permission。原来源、旧应用和历史必须能重放校验，不迁移或篡改初始会话意图。当前尚无原授权／资源到新原生规则和OS同组的完整编译器，不能用输入任意规则或哈希替代这一缺口。


## 非法原生JSON的确定前置拒绝

完整载荷预检还覆盖不可序列化对象、循环结构、非有限数和非法UTF-8：统一为内部TaskExecutionError，不让TypeError／编码异常越过原生worker错误边界；在原意图及HTTP前拒绝，不替换为默认值、不截断。已有可序列化载荷和协议容量保持。


## 原生身份JSON类型保持（11:48，先于实现）

末次核对发现Python字典相等会把metadata中的true／1／1.0视为相等，不能当精确原身份。以同一确定JSON字节比较保留类型及数组次序、忽略对象键序；接创建回执、原metadata查找与确认、原会话观察及权限before／after绑定。错误类型保持未知，不以相等数值接受关联，不扩大身份字段。补真实本机HTTP的类型漂移拒绝与恢复。


## 当前实施状态

权限单次派发与只读恢复基础、原持久外发唯一性、完整载荷／回执容量及精确JSON类型绑定已实现，并完成本轮隔离专项；原继续、启动、配置、角色／修复和Guard关联按实际证据记录。完整C39权限编译／OS同组／采用及后续会话基准仍待接入，当前字段门槛不放开。详见[本轮验证](../../../verification/v2.0/coding-native-permission-2026-11-12.md)，本文件仍pending，正式设计不自动合并。


后续接入还须处理两个具体契约：before从原创建意图加历次原已验证应用推导，不能把当前GET直接自证；C39第三步实际外发需独立RUNNING／UNKNOWN及原nonce，第四步失败仍只读原第三步。task_configuration_live_records.py与frontend/src/api/code-task-configuration.ts当前仅覆盖旧限定步骤形态，须同步扩展读取／公开投影及解码，不把第三步已可能外发的未知伪装成第二步尚未准备，也不泄露私有规则／nonce。当前尚未改这些状态，不造成公开半接入。


## 2026-11-12 18:31接续源码定位（未开放通用权限）

本轮已将受管入口逐请求执行的模型refs授权单独闭合，见[模型授权pending](WALL-E.Coding模型调用授权显式应用迭代V1_V_2.0.md)。这不改变本文件完整原生权限接入的未完成状态，后续不重做该模型分支。

- 原始输入：task_instance_driver.py的TaskLaunchInstallation.coding仍为固定NativeCodingPolicy，opencode_task_launch.py的TaskExecutionPlan只固定binary／运行包／进程／内存及endpoints。公开SCOPE目录只给scope_kind／scope_ref，不能将引用字符串直接当真实路径或网络策略；须复用服务器登记的实际对象与已核对边界，不能让HTTP规则构造器承担准入。
- 原操作身份：TaskInstanceDriver._native_actions当前仅对SuccessorSessionScope构造独立action_scope。C39第三步需自身原operation／step3／nonce，不能借原START第四步域写permission意图；task_native_actions.py已有单次发布与只读observe方法，沿原私有记录复用，不另建重试服务。
- 原状态契约：task_live_configuration.py当前_current／_unknown将未采用的限定操作归于第二步观察；task_configuration_live_records.py公开投影也只允许第二步UNKNOWN，frontend/src/api/code-task-configuration.ts的pendingStates未包含RUNNING。新增第三步实际外发时须先同步这些读取／投影／解码及恢复边界，再接生产驱动；不能让原生可能已改权限的状态冒充第三步PENDING。
- 原策略依据：observe_created_session／observe_control_configuration当前以原创建意图为expected。接通合法变更后须按同原会话与代次的已验证应用推导before／after，原GET仅作核对；第四步失败仍只观察原第三步，不重PATCH，不让Task最新引用覆盖历史来源。
- 完成条件：原生最终有序规则、当前agent／model、GET config/providers/session及实际受管目录／命令／网络采用同一固定组；旧runLoop及相关活动已封闭，才允许事务采用。当前并未保存此批生产半接入，其他scope门槛保持拒绝。正式系统安装及真实供应方另按当轮授权，不从本记录推导许可。
