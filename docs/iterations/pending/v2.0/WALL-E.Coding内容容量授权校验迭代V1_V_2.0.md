# Coding内容容量授权校验 V1

2026-11-11香港22:29，BE 0.17-draft-17，正式AuthorizationScope／ExecutionLimits、APP-CODE-CONDITIONS及7.2.1—7.2.6。独立pending，先于本单元代码。

## 发现及实际边界

22:29接续核对时，共享capture_package_limits只读取ExecutionProfileVersion，未读取更小的已批准授权容量；而profile_scope_error明确允许授权小于配置。该函数进入候选构建／封存／发布／历史读取及Plan构建／读取，是实际保护缺口，不能以配置表记录较小值代替程序约束。原项目检查输出及模型等已有较小值算法分开保留。

本单元不允许C39更换固定内容规则或容量，不新增数据迁移、Schema或授权。复用原成功START第五步骤冻结的profile_id／authorization_id及原授权不可变scope；当前C39只允许非内容字段，原授权可已RETIRED，历史读取不得误要求其仍EFFECTIVE或改用后来新组的可变引用。针对实际task_id验证原START／原授权归属、同固定capture_rules及内容限额，再取原内容profile与原授权各项较小值。

## 输入、输出及不变量

capture_package_limits必须有task_id，所有生产调用方显式传入所属任务。原START及授权缺失／不一致即不可用，不回退到profile上限。新旧候选／Plan仍用各自固定内容profile与原封存包，容量原单位不改：文件／总字节／文件数／清单／枚举／捕获时间／Git输出有界。原STOP／历史、未知恢复及C39身份保持。

不新增原生模型消息／检查／重捕获；普通GET只验证原内容，不补包。测试使用实际Schema200、NTFS／MinGit和隔离授权：较小文件上限必须在封存前拒绝超限候选，不生成可引用结果；正常原候选／历史／C39及Guard回归独立。原生运行仍按各专项实际边界记录。

## 当前状态

本限定单元已实现并完成相关隔离验证：原内容授权较小值、历史／归属、原worker确定失败及未知门槛、实际HTTP前端解码和认证Guard均见[本轮验证](../../../verification/v2.0/coding-check-configuration-2026-11-11.md)。正式设计仍待用户明确合并；不表示V2.0整体／真实供应方验收完成。允许本轮隔离相关Windows／SQLite／Guard、类型／格式／构建；不含正常业务库、服务更新、真实模型或计数、SYSTEM／WFP、提交推送。所有源码原子保存、自有Job及临时目录收尾规则保持。

## Git单次时间与总捕获时间（22:40）

复核发现固定Git内容派发只采用上层剩余捕获时间。max_git_seconds作为独立上限不能仅存入设置字典却不使用；程序在真实CandidateGitDispatch（Plan子类复用）派发前以原START不可变授权重核，单次Git deadline取剩余总捕获时间及原配置／授权max_git_seconds较小值，输出同样不超过授权max_git_output_bytes。总捕获时间仍独立，不把每次Git额度重置为总额度。

后续真实Guard夹具明确给内容包足够容量、授权Git单次15秒（profile更大），观察传入真实_FixedGitRun.run的deadline且仍运行原认证Guard／命令及收尾。未用固定sleep代替真实证据，未修改正常授权。

## 已知容量失败与未知结果的收尾（22:58，先于本补充代码）

原CandidateCaptureWorker统一把本地容量拒绝记UNKNOWN，会使无可引用结果的确定超限长期占用原操作。增加窄分支：只识别可信内部ContentManifestError／ConfigReadError／WorkspaceWriteError的明确容量代码；只用于本轮全新CAPTURE调用，不用于重启／原发布恢复。异常调用已返回并关闭本轮局部读句柄、无retained_owner／原派发保留、无待定命令、无seal／最终包、原控制版本／代次／候选仍匹配时，同事务把CAPTURE及原操作FAILED，未执行PUBLISH／CHECK取消，并更新Task控制版本。公开沿CONTENT_NOT_READY及既有FAILED投影，不伪造空候选／检查，不自动重读源或放大上限。

STOP／预算等版本竞争、清理或命令未知、已有封存／发布、一般I/O及来源不明继续UNKNOWN，不凭“目录不存在”单独判断未发生。失败暂存仍属原业务私有资源，随原任务收尾，不清正式包。相关界面显示既有捕获失败，修正固定内容配置需新任务；不自动重开模型写入窗口或继续AI。验证实际NTFS文件／清单超限经过真实worker分支、原操作FAILED、Task／操作GET正常、无候选且不自动重试；普通未知／恢复与已知成功分开。

## 收尾所有权栅栏（23:20）

异常处理及最终UNKNOWN记录前均重核当前进程锁。若容量核对途中所有权引用失效，原执行者既不能提交FAILED，也不能回退写UNKNOWN；原事实留给新所有者按原身份恢复。专项只在本轮隔离对象上模拟所有权断言失效，不释放／伪造正常服务的锁，也不声称完成真实双进程接管验收。
